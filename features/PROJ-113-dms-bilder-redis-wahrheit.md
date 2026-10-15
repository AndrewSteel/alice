# PROJ-113: DMS-Bilder in die Redis-Wahrheit aufnehmen (Lifecycle + Reconcile für Image)

## Status: Planned
**Created:** 2026-10-15
**Last Updated:** 2026-10-15

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
