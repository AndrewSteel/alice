# PROJ-113: DMS-Bilder in die Redis-Wahrheit aufnehmen (Lifecycle + Reconcile für Image)

## Status: Approved
**Created:** 2026-10-15
**Last Updated:** 2026-10-15 (QA bestanden)

## Dependencies
- Baut auf: PROJ-19 (Redis-Karten `alice:dms:path_to_hash` / `alice:dms:hash_to_paths:<hash>`), PROJ-21/PROJ-44 (Scanner → `alice/dms/lifecycle`, `delete_file`), PROJ-56 (Bild-Extraktion), PROJ-97 (Reconcile + Orphan-Cleanup)
- Betrifft die n8n-Workflows: `alice-dms-processor`, `alice-dms-path-worker`, `alice-dms-scanner`, `alice-dms-lifecycle`, `alice-dms-reconcile`
- Entlastet: PROJ-111 (LLM-Gateway) — das stündliche Neu-Beschreiben bekannter Bilder entfällt

## Kontext

Redis ist die Quelle der Wahrheit dafür, welche Dateien in den DMS-Pfaden existieren. Alle abgeleiteten Daten, auch die Weaviate-Objekte, sollen dieser Wahrheit folgen. Beim Image-Description-Backfill (PROJ-96/112) ist aufgefallen, dass Weaviate viele `Image`-Objekte mit Pfaden enthält, die es nicht mehr gibt. Die Analyse vom 2026-10-15 hat diese Ursachen gefunden:

1. **Bilder fehlen in der Redis-Wahrheit.** Der Bild-Zweig des Processors (`Code: Process Image Item`) setzt nur `alice:dms:processed`, aber weder `path_to_hash` noch `hash_to_paths` (der Dokumenten-Zweig setzt beide). Die Folgen:
   - `Code: Find Stale Paths` im Scanner kennt keine Bildpfade und erkennt gelöschte Bilder deshalb nie, sodass für Bilder nie ein `delete_file` gesendet wird.
   - Der Path-Worker stuft jedes bekannte Bild bei jedem Scan als `new` ein und schickt es erneut an `dms-extractor-image`, was jedes Mal eine LLM-Beschreibung auslöst, die der Processor dann als Duplikat verwirft. Live gemessen: Ordner `Haus` stündlich 369 „neue" Dateien, `/mnt/nas/pictures` 870 von 870 „neu" bis zum Zeitlimit von 2 h. Weil jeder Lauf von vorn beginnt, kommt der Bilder-Scan nie über die ersten ~870 Dateien hinaus.
   - Beim Duplikat-Durchlauf hängt der Processor den eigenen Hauptpfad an `additionalPaths` an.
2. **`alice-dms-lifecycle` kennt die Collection `Image` nicht.** `Code: Weaviate Find by Hash` durchsucht `Image` nicht und fragt nur das Feld `fileHash` ab (bei `Image` heißt es `file_hash`).
3. **`alice-dms-reconcile` prüft keine Bilder.** Die Image-Abfrage verlangt das Feld `file_name`, das keine `Image`-Objekte haben. Der GraphQL-Fehler führt dazu, dass die Collection stillschweigend übersprungen wird (Live-Lauf: `checked: 1505`, ohne die ~25.000 Bilder; PROJ-97-Abnahme: `2262`).
4. **Lücken im Scanner (alle Dateitypen):** Der Redis-Eintrag wird gelöscht, *bevor* die MQTT-Nachricht gesendet ist. Und wenn eine gelöschte Datei unter einem anderen Pfad weiterlebt, wird Weaviate (Haupt- und Zusatzpfade) nicht angepasst.
5. **Zeitplan des Reconcile:** `0 0 1-7 * 1` läuft wegen der ODER-Verknüpfung der Tagesfelder jeden Montag *und* an den Tagen 1–7 des Monats.

## User Stories

- Als Admin möchte ich, dass gelöschte Bilder automatisch aus der DMS-Suche verschwinden, damit die Suche nur Bilder liefert, die es noch gibt.
- Als Admin möchte ich, dass ein verschobenes Bild in Weaviate mit seinem neuen Pfad geführt wird, statt gelöscht und neu beschrieben zu werden.
- Als Admin möchte ich, dass bekannte Bilder nicht bei jedem Scan neu an das Vision-Modell gehen, damit die GPU für Chat/Sprache und echte neue Inhalte frei bleibt.
- Als Admin möchte ich, dass der Bilder-Scan alle Dateien in `/mnt/nas/pictures` erreicht, damit auch neue Bilder tief im Verzeichnisbaum erfasst werden.
- Als Admin möchte ich, dass ein kurzzeitig nicht erreichbares NAS nicht dazu führt, dass massenhaft DMS-Objekte gelöscht werden.
- Als Admin möchte ich, dass Weaviate bei jedem stündlichen Scan der Redis-Wahrheit folgt und der Reconcile nur noch als Sicherheitsnetz dient.

## Acceptance Criteria

### A) Redis-Karten für Bilder (laufender Betrieb)
- [ ] Wird ein Bild neu in Weaviate angelegt, stehen danach `path_to_hash[<pfad>] = <hash>` und `<pfad> ∈ hash_to_paths:<hash>` in Redis (wie bei Dokumenten)
- [ ] Wird ein Bild als Duplikat erkannt (gleicher Hash, anderer Pfad), stehen danach ebenfalls beide Karteneinträge für den neuen Pfad in Redis
- [ ] Nach der Verarbeitung ist der Hash des Bildes nicht mehr in `alice:dms:queued_files` (wie bei Dokumenten)
- [ ] Ein bereits verarbeitetes Bild, dessen Pfad und Hash unverändert sind, wird beim nächsten Scan als „bereits verarbeitet" übersprungen und **nicht** erneut an `dms-extractor-image` gesendet
- [ ] Der eigene Hauptpfad (`file_path`) eines Bildes steht nie zusätzlich in dessen `additionalPaths`

### B) Einmaliger Nachtrag für bestehende Bilder
- [ ] Für alle bestehenden `Image`-Objekte, deren Datei (Haupt- oder Zusatzpfad) existiert, werden die fehlenden Einträge in `path_to_hash` und `hash_to_paths` nachgetragen
- [ ] Pfade nicht existierender Dateien werden **nicht** eingetragen (Redis enthält nur existierende Dateien)
- [ ] Der eingetragene Hash entspricht dem tatsächlichen Dateiinhalt; weicht er vom in Weaviate gespeicherten `file_hash` ab, wird der Pfad nicht als bekannt eingetragen (das Bild durchläuft dann den normalen Weg „Datei geändert")
- [ ] Der Nachtrag löst **keine** LLM-Beschreibung aus
- [ ] Bestehende `additionalPaths`, die den eigenen Hauptpfad enthalten, werden bereinigt
- [ ] Der Nachtrag kann wiederholt ausgeführt werden, ohne Doppel-Einträge zu erzeugen, und meldet als Ergebnis Zähler: geprüft, eingetragen, Datei fehlt, Hash abweichend

### C) Scanner: Weaviate folgt der Wahrheit beim Scan (alle Dateitypen)
- [ ] Gelöschte Bilder werden beim stündlichen Scan erkannt; gibt es keinen weiteren existierenden Pfad mit demselben Hash, wird `delete_file` gesendet
- [ ] Ein Redis-Eintrag wird erst entfernt, wenn die zugehörige MQTT-Nachricht erfolgreich gesendet wurde; schlägt das Senden fehl, bleibt der Eintrag stehen und der Fall wird beim nächsten Scan erneut erkannt
- [ ] Lebt eine gelöschte Datei unter einem anderen existierenden Pfad weiter, wird Weaviate angepasst: Ist der gelöschte Pfad der Hauptpfad, wird ein existierender Pfad neuer Hauptpfad; der gelöschte Pfad verschwindet aus `additionalPaths`
- [ ] Ein vollständiger Scan von `/mnt/nas/pictures` schließt innerhalb des Zeitlimits des Path-Workers ab, sobald bekannte Bilder nicht mehr neu eingereiht werden (Messung nach dem Nachtrag)

### D) Lifecycle unterstützt `Image`
- [ ] `alice-dms-lifecycle` findet `Image`-Objekte über ihren Hash (Feld `file_hash`)
- [ ] `delete_file` für ein Bild löscht das `Image`-Objekt und dessen Thumbnail
- [ ] `add_path` / `update_path` für ein Bild aktualisieren `additionalPaths` bzw. `file_path` des `Image`-Objekts
- [ ] Für alle übrigen Collections bleibt das Verhalten unverändert

### E) Reconcile prüft `Image`
- [ ] `alice-dms-reconcile` prüft alle `Image`-Objekte; `checked` umfasst danach auch die Bilder
- [ ] Für `Image` gelten dieselben Regeln wie für Dokumente (PROJ-97): Datei existiert → gesund; Hash existiert an anderem Pfad → Pfad korrigieren; nirgends eine Datei → Objekt + Thumbnail löschen, tote Redis-Einträge entfernen
- [ ] Fehlt bei einer Collection ein abgefragtes Feld, wird das protokolliert und die Collection trotzdem geprüft (kein stilles Überspringen)
- [ ] Der Zeitplan läuft wöchentlich, montags 00:00 UTC, und an keinen anderen Tagen

### F) Schutz vor Massenlöschung (Scanner + Reconcile)
- [ ] Vor dem Löschen eines Objekts wird geprüft, ob die NAS-Freigabe des betroffenen Pfads (z.B. `/mnt/nas/pictures`) erreichbar ist; ist sie es nicht, wird für diese Freigabe nichts gelöscht und das protokolliert
- [ ] Würde ein Lauf mehr als **20 %** der Objekte einer Collection löschen, bricht er für diese Collection ohne Löschungen ab und meldet das (Wert konfigurierbar)
- [ ] Die Obergrenze kann für einen einzelnen manuellen Reconcile-Lauf per Parameter aufgehoben werden (für die Erstbereinigung der Bilder)

### G) Erstbereinigung
- [ ] Nach dem Nachtrag (B) läuft direkt ein echter Reconcile-Lauf (kein vorgeschalteter Dry-Run) mit aufgehobener Obergrenze, die Mount-Prüfung bleibt aktiv
- [ ] Danach existiert für jedes `Image`-Objekt in Weaviate die Datei unter seinem Hauptpfad (`file_path`); Objekte ohne irgendeine existierende Datei sind gelöscht
- [ ] Der Image-Description-Backfill findet danach nur noch Bilder mit existierender Datei (`still_failed` mit Grund „no_file" geht gegen 0)

## Edge Cases

- **NAS-Freigabe nicht eingehängt** während Scan oder Reconcile: Für diese Freigabe wird nichts gelöscht; Redis-Einträge bleiben erhalten; Wiederholung beim nächsten Lauf.
- **Datei ersetzt (gleicher Pfad, anderer Inhalt):** Weiterhin Ablauf „Datei geändert" (alter Hash wird entfernt, neue Verarbeitung) — auch für Bilder.
- **Gleiches Bild an mehreren Pfaden, einer davon gelöscht:** Kein `delete_file`; Weaviate-Pfade werden angepasst (C).
- **Alle Pfade eines Bildes gelöscht:** `delete_file` → Objekt + Thumbnail weg; Redis-Einträge des Hashes entfernt.
- **MQTT-Broker beim Scan nicht erreichbar:** Kein Redis-Eintrag wird entfernt; beim nächsten Scan erneut erkannt.
- **Weaviate-Objekt existiert nicht (mehr):** Lifecycle protokolliert und überspringt (bestehendes Verhalten).
- **Bild in Weaviate, Datei existiert, aber Hash weicht ab** (Datei wurde bearbeitet): Nachtrag trägt es nicht als bekannt ein; der nächste Scan behandelt es als geändert.
- **Obergrenze greift im normalen Betrieb** (z.B. großer Ordner bewusst verschoben/gelöscht): Lauf bricht für die Collection ab; Admin entscheidet und startet manuell mit aufgehobener Obergrenze.
- **Gleichzeitige Läufe** von Reconcile, Processor und Backfills: bestehender gemeinsamer Lock bleibt maßgeblich.

## Außerhalb des Scopes

- Collection `Email` (→ PROJ-98).
- Grundsätzlicher Umbau des Path-Workers auf inkrementelles Scannen (z.B. nach Änderungsdatum). Erreicht (C) „vollständiger Bilder-Scan im Zeitlimit" das nicht, wird das ein eigenes Feature.
- Neu-Beschreibung bestehender Bilder.
- Änderungen an `dms-extractor-image`.

## Technical Requirements (optional)
- Der Nachtrag (B) muss die ~25.000 bestehenden Bilder verarbeiten können, ohne das n8n-Speicherlimit zu sprengen (Muster der bestehenden Backfills: Zeitlimit, Selbstfortsetzung, Lock).
- Konfigurierbar: Löschobergrenze (Default 20 %).
- Workflow-Deployments erfolgen durch den Nutzer.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

Kein neuer Dienst und kein neuer Workflow. Fünf bestehende n8n-Workflows werden angepasst. Der Grundsatz: **Redis wird nur aus dem echten Dateisystem befüllt (Scan), und Weaviate folgt Redis.** Redis-Einträge werden erst entfernt, wenn Weaviate angepasst ist.

```
Dateisystem (NAS)
      |
  alice-dms-scanner  (stündlich)
      +-- Path-Worker je Ordner: hasht Dateien
      |     +-- neu ................................. -> Extractor -> Processor (trägt Bild jetzt in Redis ein)  [geändert]
      |     +-- bekannt, aber ohne Pfad-Eintrag ..... -> Selbstheilung: Pfad in Redis eintragen, kein LLM       [NEU]
      |     +-- Fortsetzung nach Zeitlimit .......... -> nächster Lauf macht dort weiter                       [NEU]
      +-- Find Stale Paths: vergleicht Redis mit Dateisystem
            +-- Datei weg, keine Kopie mehr ......... -> delete_file  --+
            +-- Datei weg, Kopie lebt woanders ...... -> remove_path  --+--> alice-dms-lifecycle         [NEU/geändert]
            +-- Schutz: Freigabe erreichbar? Anteil <= 20 %?            |      +-- findet jetzt auch Image
                                                                        |      +-- passt Weaviate an (inkl. Thumbnail)
                                                                        |      +-- danach erst Redis-Einträge aufräumen
alice-dms-reconcile  (wöchentlich, Sicherheitsnetz)                     v
      +-- prüft jetzt auch Image, gleiche Regeln + gleicher Schutz    Weaviate
```

### A) Komponenten (Workflows) und Änderungen

```
alice-dms-processor  (Bild-Zweig "Code: Process Image Item")
+-- Neues Bild eingefügt   -> path_to_hash + hash_to_paths setzen, queued_files aufräumen   [NEU]
+-- Duplikat erkannt       -> dto. für den neuen Pfad; eigener Hauptpfad wird nie Zusatzpfad [geändert]

alice-dms-path-worker
+-- Selbstheilung (Lifecycle Check)                                                         [NEU]
|   "Hash verarbeitet, aber kein Pfad bekannt" -> Weaviate-Objekt mit diesem Hash vorhanden?
|     +-- ja:   Pfad in Redis eintragen; ist der Pfad weder Haupt- noch Zusatzpfad -> als Zusatzpfad ergänzen
|     +-- nein: wie bisher "neu" (normale Verarbeitung)
+-- Fortsetzung nach Zeitlimit                                                              [NEU]
|   feste Reihenfolge der Dateien; beim Zeitlimit wird die Position gemerkt,
|   der nächste Lauf überspringt bis dorthin; am Ordnerende wird die Marke gelöscht
+-- Zähler "registered" (selbstgeheilt) in der Lauf-Zusammenfassung                        [NEU]

alice-dms-scanner  ("Code: Find Stale Paths")
+-- erkennt nur noch, verändert Redis nicht mehr selbst                                    [geändert]
+-- delete_file (keine lebende Kopie) / remove_path (Kopie lebt woanders)                  [remove_path NEU]
+-- Schutz: Freigabe nicht erreichbar -> keine Meldungen für diese Freigabe                  [NEU]
+-- Schutz: > 20 % der Einträge einer Freigabe betroffen -> keine Meldungen, Warnung        [NEU]

alice-dms-lifecycle
+-- Suche nach Hash auch in Image (Feld file_hash)                                         [NEU]
+-- delete_file: Weaviate-Objekt (+ Bankumsätze) + Thumbnail löschen, DANN Redis aufräumen   [geändert]
+-- remove_path: toten Pfad aus Weaviate entfernen (ggf. neuer Hauptpfad), DANN Redis       [NEU]
+-- add_path / update_path: auch für Image                                                 [geändert]

alice-dms-reconcile
+-- Image-Abfrage ohne file_name; fehlende Felder generell weglassen + protokollieren       [geändert]
+-- Image: eigener Hauptpfad / tote Pfade aus Zusatzpfaden entfernen                        [NEU]
+-- Vorab-Zählung je Collection -> Obergrenze 20 % (per Parameter aufhebbar)                 [NEU]
+-- Freigabe-Erreichbarkeit vor jedem Löschen                                               [NEU]
+-- Zeitplan: montags 00:00 UTC                                                             [geändert]
```

### B) Daten

Keine neuen Datenbanken oder Collections, keine neuen Weaviate-Felder.

- **Redis (bestehende Karten):** `path_to_hash` und `hash_to_paths:<hash>` enthalten künftig auch Bilder.
- **Redis (neu):** je Ordner eine Fortsetzungsmarke (zuletzt fertig verarbeitete Datei), wird am Ordnerende gelöscht.
- **MQTT `alice/dms/lifecycle`:** neue Aktion `remove_path` (Hash, toter Pfad, lebende Pfade).
- **Konfiguration:** Löschobergrenze (Default 20 %).

### C) Tech-Entscheidungen (begründet)

1. **Nachtrag per Selbstheilung im Scan statt eigenem Workflow** (Entscheidung Nutzer). Nur der Scan sieht das echte Dateisystem: Der Hash kommt aus dem tatsächlichen Dateiinhalt, und auch verschobene Bilder werden unter ihrem neuen Pfad gefunden. Ein Nachtrag aus Weaviate heraus würde verschobene Bilder als verwaist löschen und später neu beschreiben lassen. Die Prüfung „Weaviate-Objekt vorhanden" verhindert, dass ein Hash als bekannt gilt, zu dem es kein Objekt gibt.

2. **Fortsetzung nach Zeitlimit.** Der Bilder-Ordner braucht nach Messung (~0,45 s pro bekannter Datei) für ~25.000 Bilder ca. 3 h, mehr als das 2-h-Limit. Ohne Fortsetzung erreicht der Scan die hinteren Dateien nie. Das ist kein inkrementelles Scannen (außerhalb des Scopes), es verteilt nur einen vollständigen Durchlauf auf mehrere Läufe. **Damit gilt AC C4 als „vollständiger Durchlauf über mehrere Läufe".** Neue Dateien weiter hinten im Baum werden dadurch spätestens nach einem vollen Zyklus (ca. 2–3 Stunden) erfasst.

3. **Redis wird beim Verbraucher aufgeräumt, nicht beim Scanner.** Der Scanner meldet nur noch. Der Lifecycle passt erst Weaviate an und entfernt danach die Redis-Einträge. Geht eine Nachricht verloren oder scheitert Weaviate, bleibt der Eintrag stehen und der nächste stündliche Scan meldet erneut. Doppelte Meldungen sind harmlos (Objekt nicht gefunden → überspringen). Das erfüllt AC C2 robuster als „erst senden, dann löschen" im Scanner.

4. **Neue Aktion `remove_path` statt Wiederverwendung von `update_path`.** `update_path` bedeutet „Datei verschoben, alle alten Pfade weg". `remove_path` bedeutet „ein Pfad weg, Kopien leben weiter". Die getrennte Aktion hält beide Fälle eindeutig.

5. **Schutz vor Massenlöschung an zwei Stellen.** Die Erreichbarkeit der Freigabe (z.B. `/mnt/nas/pictures`) wird über das Wurzelverzeichnis der Freigabe geprüft: lesbar und nicht leer. Im **Scanner** gilt die 20-%-Grenze je Freigabe, weil der Scanner keine Collections kennt. Im **Reconcile** gilt sie je Collection wie in der Spec; dafür zählt er vor dem ersten Löschen, wie viele Objekte er löschen würde.

6. **Thumbnail-Löschung im Lifecycle für alle Collections.** Bisher räumt nur der Reconcile Thumbnails weg. Der Lifecycle nutzt künftig denselben Thumbnailer-Aufruf, damit `delete_file` vollständig ist.

7. **Reconcile: fehlende Felder generell abfangen.** Die bestehende Ausnahme für `thumbnail_path`/`additionalPaths` wird verallgemeinert. Fehlt ein abgefragtes Feld, wird es weggelassen, protokolliert und die Abfrage wiederholt. Eine Collection wird nie mehr still übersprungen.

### D) Abläufe

**Laufender Betrieb (stündlich):** Scan → neue Bilder wie bisher an den Extractor, und der Processor trägt sie jetzt in Redis ein. Bekannte Bilder ohne Eintrag werden selbstgeheilt. Gelöschte Dateien gehen als `delete_file`/`remove_path` an den Lifecycle, der erst Weaviate und dann Redis anpasst.

**Erstinbetriebnahme (ersetzt AC B/G-Ablauf):**
1. Alle fünf Workflows deployen.
2. Die stündlichen Scans laufen. Jeder Ordner ist einmal vollständig durchlaufen, sobald seine Lauf-Zusammenfassung ohne Zeitlimit-Abbruch endet (Bilder-Ordner: voraussichtlich 2 Läufe). Die Zähler `registered` zeigen den Fortschritt der Selbstheilung.
3. Dann ein **echter** Reconcile-Lauf per Webhook mit aufgehobener Obergrenze und ausreichendem Zeitlimit. Die Prüfung der Freigaben bleibt aktiv.
4. Danach gilt der wöchentliche Zeitplan.

**Fehlerfälle:**
- Freigabe nicht erreichbar → keine Meldungen bzw. Löschungen für diese Freigabe, Warnung im Log.
- Obergrenze überschritten → keine Löschungen für diese Freigabe/Collection, Warnung im Log.
- MQTT oder Weaviate gestört → Redis bleibt unverändert, der nächste Scan meldet erneut.
- Selbstheilung findet kein Weaviate-Objekt → das Bild wird wie bisher als neu verarbeitet.

### E) Anpassungen der Spec durch das Design

- **B (Nachtrag):** „Einmaliger Nachtrag" erfolgt durch die Selbstheilung im regulären Scan. Statt eines eigenen Ergebnisses mit Zählern gibt es den Zähler `registered` je Ordnerlauf. „Datei fehlt" erfasst der Reconcile (`deleted_orphan` bzw. `path_repaired`). „Hash abweichend" führt automatisch zum Ablauf „Datei geändert". Die Bereinigung des eigenen Hauptpfads in `additionalPaths` übernimmt der Reconcile.
- **C4:** „vollständiger Scan im Zeitlimit" → „vollständiger Durchlauf, ggf. über mehrere Läufe mit Fortsetzung".
- **F:** Im Scanner gilt die Obergrenze je Freigabe statt je Collection.
- **G:** Der Reconcile-Erstlauf startet erst nach dem ersten vollständigen Durchlauf aller Ordner (sonst würden verschobene Bilder gelöscht).

### F) Abhängigkeiten (Pakete)

Keine neuen Pakete. Genutzt werden die bereits in n8n verfügbaren Module (Redis, axios, fs) sowie der Thumbnailer-Dienst (`DELETE /thumbnail/<uuid>`).

### G) Betroffene Dateien

- `workflows/alice-dms-processor.json`, `alice-dms-path-worker.json`, `alice-dms-scanner.json`, `alice-dms-lifecycle.json`, `alice-dms-reconcile.json`
- Keine Änderung an `sql/`, Frontend, nginx oder Containern
- Deployment durch den Nutzer: zuerst Lifecycle (versteht `remove_path`), dann Processor, Path-Worker, Scanner, Reconcile

## Implementation Notes (Backend, 2026-10-15)

Geänderte Dateien: die fünf Workflows (`alice-dms-processor`, `-path-worker`, `-scanner`, `-lifecycle`, `-reconcile`) sowie `docker/compose/automations/n8n/compose.yml` + `.env.example` (neue Variable `DMS_DELETE_MAX_RATIO`, Default `0.2`; ohne gesetzte Variable gilt im Code ebenfalls 0,2).

**Processor (`Code: Process Image Item`):** neue und als Duplikat erkannte Bilder werden in `path_to_hash`/`hash_to_paths` eingetragen, `queued_files` wird aufgeräumt. Der eigene Hauptpfad kommt nie in `additionalPaths`, und bestehender Schmutz wird beim Duplikat-Durchlauf gleich mit bereinigt. „Datei ersetzt“ (gleicher Pfad, anderer Hash in `path_to_hash`) löst das alte `Image`-Objekt: Pfad entfernen, Kopie wird Hauptpfad, oder Objekt + Thumbnail löschen.

**Path-Worker:**
- Selbstheilung in `Code: Lifecycle Check`: Ist für einen Hash kein Pfad bekannt, wird Weaviate gefragt (Bilder → `Image`, sonst Dokument-Collections). Bei einem Treffer wird der Pfad in Redis eingetragen (+ `processed`, − `queued_files`), ggf. als Zusatzpfad ergänzt und als `registered_files` gezählt. Es gibt keinen Extractor-/LLM-Aufruf. Ist Weaviate nicht erreichbar, wird die Datei in diesem Lauf übersprungen und nicht an das LLM geschickt.
- Feste Reihenfolge (sortiert) und Fortsetzungsmarke `alice:dms:scanner:resume:folder:<id>`. Ein Durchlauf, der von vorn beginnt, setzt `…:pass_start:folder:<id>`. Am Ordnerende wird die Marke gelöscht und `…:last_full_pass:folder:<id>` gesetzt. Die Zusammenfassung enthält `registered_files` und `full_pass_completed`.

**Scanner (`Code: Find Stale Paths`):** meldet nur noch `delete_file` bzw. die neue Aktion `remove_path` (mit `alive_paths`) und verändert Redis nicht mehr. Schutz: Ist die Freigabe `/mnt/nas/<share>` nicht lesbar oder leer, wird für sie nichts gemeldet. Liegt der fehlende Anteil je Freigabe über `DMS_DELETE_MAX_RATIO`, wird für diese Freigabe nichts gemeldet und eine Warnung geloggt. Der MQTT-Knoten heißt jetzt `MQTT: Publish lifecycle (stale path)`.

**Lifecycle:** findet `Image` (`file_hash`/`file_path`). Ein fehlgeschlagener Lookup wird von „nicht gefunden“ unterschieden: Bei `delete_file`/`remove_path` wird dann ein Fehler geworfen und Redis bleibt unverändert. `delete_file` löscht Thumbnail + Objekt (404 = schon weg) und räumt **danach** Redis auf. Neuer Zweig `IF: Is remove_path` → `Code: Handle remove_path` → `MQTT: Done (remove_path)`. `add_path`/`update_path` nutzen das richtige Pfadfeld, der Hauptpfad kommt nie in `additionalPaths`, und tote alte Pfade fliegen bei `update_path` aus `additionalPaths`.

**Reconcile:**
- Die `Image`-Abfrage enthält kein `file_name` mehr. Fehlt ein Feld im Schema, wird es generisch weggelassen und geloggt; fehlt Pfad- oder Hash-Feld, landet das in `collection_errors`.
- Gesunde Objekte werden schon in `Code: Query Weaviate` gezählt und laufen nicht durch die Schleife (wichtig bei ~24.000 Bildern).
- Eine Vorab-Zählung `would_delete` je Collection prüft die Obergrenze (Parameter `ignore_delete_limit=true` hebt sie auf). Ein Objekt, dessen Freigabe nicht erreichbar ist, wird behalten (`skipped_unreachable`).
- Der eigene Hauptpfad und tote Pfade werden aus `additionalPaths` entfernt (`additional_paths_cleaned`). Ein lebender Zusatzpfad zählt als Kandidat bei der Pfadkorrektur, statt dass das Objekt gelöscht wird.
- Der Zeitplan heißt jetzt `0 0 * * 1` (Knoten `Schedule Trigger: Weekly`).
- **Mitbehobener Bug:** `SHA256_RE` erwartete 64 Hex-Zeichen ohne Präfix, gespeichert wird aber `sha256:<hex>`. Dadurch griffen die Pfadkorrektur über den Hash und das Redis-Aufräumen im Reconcile bisher nie.

### Abweichungen vom Tech Design
1. **Karenz bis zum vollständigen Durchlauf (neu):** Der Scanner prüft zu Beginn jedes Laufs, die Path-Worker laufen asynchron und finden ein verschobenes Bild oft erst Stunden später. Ohne Karenz würde ein verschobenes Bild gelöscht und neu beschrieben, was der User Story widerspricht. Deshalb merkt sich der Scanner das erste Fehlen in `alice:dms:scanner:missing_since` und meldet einen Pfad erst, wenn **alle** aktiven Ordner danach einen vollständigen Durchlauf begonnen und beendet haben. Folge: Gelöschte Dateien verschwinden mit Verzögerung (bei Bildern ca. ein Bilder-Zyklus, ~3–4 h Scanzeit) statt beim nächsten Lauf. Nach dem Deployment meldet der Scanner erst etwas, wenn jeder Ordner einmal komplett durchlaufen ist, was auch als Schutz während der Selbstheilung dient.
2. **Selbstheilung auch für nicht verarbeitete Hashes:** Die Weaviate-Prüfung greift immer, wenn für einen Hash kein Pfad bekannt ist, nicht nur bei `processed`. Grund: Live hängen 24.331 Hashes in `queued_files` (der Bild-Zweig hat dort nie aufgeräumt), und solche Bilder wären sonst als `already_queued` dauerhaft übersprungen worden. Kosten: eine GraphQL-Abfrage je wirklich neuer Datei.
3. **`additionalPaths`-Bereinigung im Reconcile für alle Collections**, nicht nur `Image` (gleiche Regel, kein Sonderfall).
4. Keine Mindestanzahl für die Obergrenze: Bei sehr kleinen Collections kann schon eine Löschung über 20 % liegen. Dann entscheidet der Admin (siehe Edge Case), und die Grenze lässt sich per Variable anpassen.

### Verifikation
- Ausführungstests (Node-Harness mit In-Memory-Redis, Fake-Weaviate/Thumbnailer, `/mnt/nas` → Temp-Verzeichnis), die die Code-Knoten direkt aus den Workflow-JSONs ausführen: **36/36 grün**. Gegenprobe mit den alten Workflows aus `HEAD`: 32/36 rot (die 4 grünen prüfen bewusst unverändertes Verhalten).
- Struktur: alle Verbindungsziele existieren, Knotennamen/IDs eindeutig; Syntax aller Code-Knoten geprüft. Die n8n-MCP-Validierung wurde nicht ausgeführt (Workflow-Größe).

### Deployment-Reihenfolge (durch den Nutzer)
1. `./scripts/sync-compose.sh` und n8n neu starten (nur nötig, wenn `DMS_DELETE_MAX_RATIO` vom Default abweichen soll)
2. Workflows: Lifecycle → Processor → Path-Worker → Scanner → Reconcile
3. Stündliche Scans laufen lassen, bis jeder Ordner `full_pass_completed: true` meldet (`alice/dms/scanner/path_stats`)
4. Echter Reconcile: `POST /webhook/alice-dms-reconcile` mit `{"confirm": true, "ignore_delete_limit": true}`

## QA Test Results

**Datum:** 2026-10-15 · **Tester:** QA (Claude) · **Umfang:** 5 n8n-Workflows (nicht deployt — Deployment durch den Nutzer)

**Methode:** Die Code-Knoten werden direkt aus den Workflow-JSONs in einem Node-Harness ausgeführt (In-Memory-Redis, Fake-Weaviate mit GraphQL/REST, Fake-Thumbnailer, `/mnt/nas` → Temp-Verzeichnis). Tests: `node --test workflows/tests/proj113/` → **46/46 grün** (36 Backend + 10 QA-Edge-Cases). Gegenprobe mit den Workflows aus dem Stand vor PROJ-113: 32/36 rot. Dazu kamen eine Strukturprüfung (Verbindungen, eindeutige Namen/IDs, Syntax), eine Regressionssuche nach weiteren Lesern der Redis-Keys und eine Durchsicht der Live-Daten (nur lesend, `ki.lan`).

### Acceptance Criteria

| AC | Kriterium | Ergebnis |
|----|-----------|----------|
| A1 | Neues Bild → `path_to_hash` + `hash_to_paths` gesetzt | PASS |
| A2 | Duplikat (anderer Pfad) → beide Karteneinträge für den neuen Pfad | PASS |
| A3 | Hash nach Verarbeitung nicht mehr in `queued_files` | PASS |
| A4 | Unverändertes Bild beim nächsten Scan „bereits verarbeitet“, kein Extractor | PASS |
| A5 | Eigener Hauptpfad nie in `additionalPaths` (Processor, Lifecycle, Reconcile-Bereinigung) | PASS |
| B1 | Fehlende Einträge für bestehende Bilder werden nachgetragen (per Selbstheilung im Scan, Design E) | PASS |
| B2 | Pfade nicht existierender Dateien werden nicht eingetragen (nur gescannte Dateien) | PASS |
| B3 | Hash = tatsächlicher Dateiinhalt; abweichender Hash → normaler Weg (kein Weaviate-Treffer → `new`/`replace`) | PASS |
| B4 | Nachtrag löst keine LLM-Beschreibung aus (`registered`, `_skip`) | PASS |
| B5 | `additionalPaths` mit eigenem Hauptpfad werden bereinigt (Reconcile + Processor-Duplikat) | PASS |
| B6 | Wiederholbar ohne Doppel-Einträge; Zähler `registered_files` (Design E) | PASS |
| C1 | Gelöschtes Bild → `delete_file`, wenn kein weiterer Pfad lebt (nach Karenz, siehe Abweichung 1) | PASS |
| C2 | Redis-Eintrag erst nach erfolgreicher Verarbeitung entfernt; bei Fehler bleibt er und wird erneut gemeldet | PASS |
| C3 | Datei lebt woanders weiter → `remove_path`, Hauptpfad wird umgesetzt, toter Pfad raus | PASS |
| C4 | Vollständiger Durchlauf über mehrere Läufe mit Fortsetzung (Logik) | PASS (Logik) · **Messung nur live** |
| D1 | Lifecycle findet `Image` über `file_hash` | PASS |
| D2 | `delete_file` löscht `Image`-Objekt + Thumbnail | PASS |
| D3 | `add_path` / `update_path` für `Image` (`additionalPaths` / `file_path`) | PASS |
| D4 | Übrige Collections unverändert (inkl. BankStatement-Kaskade) | PASS |
| E1 | Reconcile prüft alle `Image`-Objekte, `checked` enthält Bilder | PASS |
| E2 | Gleiche Regeln wie für Dokumente (gesund / Pfad korrigieren / löschen + Thumbnail + Redis) | PASS |
| E3 | Fehlendes Feld wird protokolliert, Collection trotzdem geprüft | PASS |
| E4 | Zeitplan `0 0 * * 1` (montags 00:00 UTC, sonst nie) | PASS |
| F1 | Freigabe nicht erreichbar → keine Löschungen, protokolliert (Scanner + Reconcile) | PASS |
| F2 | > 20 % → keine Löschungen, Meldung; Wert über `DMS_DELETE_MAX_RATIO` konfigurierbar (Scanner je Freigabe, Reconcile je Collection) | PASS |
| F3 | Obergrenze per Parameter `ignore_delete_limit` für einen manuellen Lauf aufhebbar; der Schedule hebt sie nie auf | PASS |
| G1 | Echter Reconcile mit aufgehobener Obergrenze, Mount-Prüfung aktiv | PASS (Logik) · **Lauf nur live** |
| G2 | Danach existiert für jedes `Image` die Datei unter `file_path` | **nur live prüfbar** |
| G3 | Backfill findet danach nur noch Bilder mit Datei (`no_file` → 0) | **nur live prüfbar** |

**Ergebnis:** 26/29 bestanden, 3 nur live prüfbar (C4-Messung, G2, G3), 0 fehlgeschlagen.

### Edge Cases

| Edge Case | Ergebnis |
|-----------|----------|
| NAS-Freigabe nicht eingehängt (leer/unlesbar) | PASS — Scanner meldet nichts und setzt keine `missing_since`-Marken; Reconcile behält das Objekt auch mit `ignore_delete_limit` |
| Datei ersetzt (gleicher Pfad, anderer Inhalt), auch für Bilder | PASS — altes `Image` gelöst (gelöscht bzw. Kopie wird Hauptpfad) |
| Gleiches Bild mehrfach, ein Pfad gelöscht | PASS — `remove_path`, kein `delete_file` |
| Alle Pfade gelöscht | PASS — `delete_file`, Objekt + Thumbnail weg, Redis bereinigt |
| MQTT/Weaviate gestört | PASS — Lookup-Fehler wirft, Redis bleibt, erneute Meldung beim nächsten Scan |
| Weaviate-Objekt existiert nicht (mehr) / doppelte Meldung | PASS — nur Redis aufgeräumt, kein Fehler, Weaviate-DELETE 404 toleriert |
| Hash abweichend | PASS — kein Weaviate-Treffer → `new`, bekannter Pfad → `replace` |
| Obergrenze greift im Normalbetrieb | PASS — Warnung + `delete_limit_blocked` / `delete_blocked` |
| Verschobene Datei (User Story) | PASS — Karenz: Path-Worker findet neuen Ort → `update_path`, Scanner löscht nicht |
| Zusätzlich: GraphQL-Injection über `file_hash` (Lifecycle, Path-Worker) | PASS — bereinigt |
| Zusätzlich: Redis beim Scanner-Sweep down | PASS — keine Meldungen, Statistik-Item bleibt |
| Zusätzlich: ungültiges `DMS_DELETE_MAX_RATIO` (`abc`, `0`, `5`, `-1`) | PASS — Fallback 0,2 |
| Zusätzlich: Datei der Fortsetzungsmarke gelöscht / Marke hinter letzter Datei | PASS — weiter bei nächstem Pfad bzw. Neustart |
| Zusätzlich: Ordner unlesbar | PASS — kein `last_full_pass` (Karenz hält Löschungen zurück) |

### Bugs

**BUG-1 (Low) — Vor dem Deployment verschobenes Bild behält bis zum Reconcile seinen toten Hauptpfad**
- *Ursache:* Die Selbstheilung (`Code: Lifecycle Check`) ergänzt einen gefundenen Pfad nur als Zusatzpfad, auch wenn der in Weaviate gespeicherte Hauptpfad nicht mehr existiert. Der tote Hauptpfad stand nie in `path_to_hash`, deshalb meldet ihn auch der Scanner nicht.
- *Reproduktion:* Test „QA: image moved BEFORE deployment …“: `Image{file_path: old/m.jpg}`, Datei liegt unter `new/m.jpg`, Redis leer → nach dem Scan steht `file_path` weiter auf `old/m.jpg`, `new/m.jpg` ist Zusatzpfad.
- *Auswirkung:* Bis zum Reconcile (Schritt 4 der Erstinbetriebnahme bzw. wöchentlich) zeigt die Suche den alten Pfad. Der Reconcile korrigiert ihn (getestet: „main path dead but additional path alive → promoted“).
- *Vorschlag:* In der Selbstheilung den gefundenen Pfad zum Hauptpfad machen, wenn der gespeicherte Hauptpfad auf erreichbarer Freigabe nicht existiert.

**BUG-2 (Medium) — Ein Ordner ohne abgeschlossenen Durchlauf hält alle Scanner-Löschungen still zurück**
- *Ursache:* Die Karenz verlangt einen vollständigen Durchlauf **aller** aktiven Ordner. Endet ein Ordner dauerhaft nie regulär (Ordner unlesbar/gelöscht, aber in `dms_watched_folders` aktiv; Lock-Verlust in jedem Lauf), wird nie etwas gemeldet. Im Log steht nur die Anzahl wartender Pfade (Info-Level), nicht welcher Ordner blockiert.
- *Reproduktion:* Test „QA: unreadable folder -> no full pass recorded“ + „C1: grace waits for EVERY folder pass“.
- *Auswirkung/Workaround:* Weaviate folgt der Wahrheit nur noch über den wöchentlichen Reconcile (der löscht verwaiste Objekte unabhängig von der Karenz). Kein Datenverlust.
- *Vorschlag:* Warnung mit den Ordner-IDs ohne aktuellen Durchlauf (z. B. älter als 24 h) in `Code: Find Stale Paths` und im Statistik-Item.

**BUG-3 (Low) — Viele Löschungen auf einmal erzeugen eine Lifecycle-Ausführung je Datei**
- *Ursache:* Bestehendes Muster (eine MQTT-Nachricht = eine n8n-Ausführung). Bis zur 20-%-Grenze können das bei `/mnt/nas/pictures` mehrere tausend parallele Ausführungen sein (z. B. ein bewusst gelöschter großer Bilderordner).
- *Auswirkung:* Kurzzeitige Last auf n8n. Kein Datenfehler (doppelte und parallele Meldungen sind idempotent getestet).
- *Vorschlag:* Bei Bedarf Folge-Feature (Bündelung oder Rate-Limit). Für PROJ-113 akzeptierbar.

### Security Audit
- Keine neuen Endpunkte und keine neuen Credentials. Neue Werte kommen nur aus Redis/Weaviate/Dateisystem bzw. aus dem internen MQTT-Topic `alice/dms/lifecycle`.
- GraphQL-Injection: `file_hash` wird in Lifecycle und Path-Worker auf `[a-zA-Z0-9:]` reduziert, im Processor escaped. Feldnamen aus Weaviate-Fehlermeldungen werden nur entfernt, wenn sie in der festen Feldliste stehen. Getestet.
- Thumbnailer-Aufruf nur mit Weaviate-UUIDs; der Endpoint validiert per Regex (PROJ-97).
- `alive_paths` aus MQTT werden vor der Nutzung gegen das Dateisystem geprüft. Wer auf das interne MQTT-Topic schreiben kann, konnte schon vorher `delete_file` auslösen, das Risiko ist also unverändert.
- Der Reconcile-Webhook bleibt ohne JWT (offener Punkt **PROJ-97 BUG-2**, Nutzerentscheidung). Neu ist nur `ignore_delete_limit`; die Freigabe-Prüfung bleibt auch dann aktiv, Schutz weiter über VPN und das `confirm`-Gate. Keine neue Lücke, die Wirkung einer missbräuchlichen Auslösung steigt aber leicht.
- Keine Secrets in Code oder Logs (Redis-Passwort weiter über `$env`).

### Regression
- Weitere Leser der Redis-Keys: `admin_dashboard.py` zählt `path_to_hash` (Bilder zählen jetzt mit, gewünscht), `alice-mail-reconcile` nutzt nur eigene Mail-Hashes. Keine Regression.
- Dokumenten-Pfade (Lifecycle `add_path`/`update_path`/`delete_file` inkl. BankStatement-Kaskade, Path-Worker `new`/`already_queued`/`replace`/`update_path`) per Test bestätigt.
- Verhaltensänderung für Dokumente (gewollt, Teil von C): Löschungen werden mit Karenz gemeldet. Pfadkorrektur und Redis-Aufräumen im Reconcile greifen durch den `sha256:`-Fix erstmals.
- Kein Frontend betroffen → keine Vitest-/Playwright-Läufe nötig.

### Nach dem Deployment live zu prüfen
1. `alice/dms/scanner/path_stats`: `registered_files` > 0 in `Haus` und `Bilder`; `new_files` für bekannte Bilder ≈ 0; beim Bilder-Ordner `resume_from` im Zeitlimit-Log, später `full_pass_completed: true` (**C4**)
2. Reconcile (`confirm`, `ignore_delete_limit`): `checked` ≈ Gesamtbestand inkl. ~24.300 Bilder; danach **G2/G3** prüfen (Backfill `no_file` → 0)
3. Redis: `HLEN alice:dms:path_to_hash` steigt auf ~25.000; `SCARD alice:dms:queued_files` sinkt deutlich

### Production-Ready-Entscheidung
**READY** — keine Critical- oder High-Bugs. 1 Medium (BUG-2, Workaround über den wöchentlichen Reconcile) und 2 Low sind dokumentiert. Drei Kriterien sind erst nach dem Deployment messbar und als Live-Checks oben festgehalten.

## Deployment
_To be added by /deploy_
