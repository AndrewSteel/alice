# PROJ-112: Panorama-/Großbild-Beschreibung im DMS (zentrale Bildbeschreibung mit Teilbild-Zerlegung)

## Status: Deployed
**Created:** 2026-10-14
**Last Updated:** 2026-10-14 (Deployed)

## Dependencies
- Betrifft: `dms-extractor-image` (`get_ai_description`, MQTT-Topic `alice/dms/image`) und n8n-Workflow `alice-dms-image-description-backfill`
- Baut auf: PROJ-96 (Backfill Auto-Fortsetzung + Zeitlimit, Deployed) — Zeitfenster, Redis-Lock, Selbstaufruf-Kette und Zählung `updated`/`still_failed` bleiben unverändert; löst PROJ-96 **BUG-5** (Panorama-Bilder → HTTP 413 + Task-Runner-Abbruch)
- Nutzt: PROJ-99 (llama.cpp-Vision-Modell auf `llama-3090`), PROJ-111 (LLM-Gateway mit Priorisierung — Bildbeschreibungen laufen als DMS-Anfragen mit niedriger Priorität)

## Kontext

Bildbeschreibungen scheitern nicht an der Dateigröße, sondern am **Seitenverhältnis**. Heute existieren zwei unabhängige Implementierungen:

1. **`get_ai_description`** im Container `dms-extractor-image` (ausgelöst über MQTT `alice/dms/image`): verkleinert die längste Seite auf 1024 px. Ein Panorama mit 22704×1760 px wird so zu 1024×79 px — die Beschreibung ist unbrauchbar.
2. **`alice-dms-image-description-backfill`** (n8n, zeitgesteuert, für Bilder mit `extraction_failed=true`): liest das Originalbild selbst ein und schickt es unverkleinert als Base64 an das LLM. Große Bilder (z.B. 52,8 MB) scheitern mit HTTP 413 bzw. bringen den n8n-Task-Runner zum Absturz.

Ziel: **eine zentrale Bildbeschreibungs-Funktion** (Eingabe: Dateipfad, Ausgabe: Beschreibungstext), die auch Bilder außerhalb der Standard-Seitenverhältnisse sinnvoll beschreibt. Der Backfill ruft diese Funktion auf, statt selbst das LLM anzusprechen. Ob die Funktion im `dms-extractor-image` verbleibt oder in einen eigenen Container wandert, entscheidet `/architecture`.

## User Stories

- Als Admin möchte ich, dass Panoramabilder (quer und hochkant) eine inhaltlich brauchbare Beschreibung erhalten, damit ich sie über die DMS-Suche wiederfinde.
- Als Admin möchte ich, dass Bildbeschreibungen an genau einer Stelle erzeugt werden, damit Laufzeit-Pfad und Backfill identische Ergebnisse liefern und Verbesserungen nur einmal umgesetzt werden müssen.
- Als Admin möchte ich, dass der Backfill auch sehr große Bilddateien verarbeiten kann, ohne dass n8n an Speichergrenzen oder Request-Größenlimits scheitert.
- Als Admin möchte ich, dass eine fehlgeschlagene Beschreibung nie als scheinbar vollständige Teil-Beschreibung gespeichert wird, damit der Backfill sie später zuverlässig erneut versucht.
- Als Admin möchte ich, dass 200-MP-Aufnahmen (z.B. Oppo Find X9 Ultra) normal beschrieben werden.

## Acceptance Criteria

### Zentrale Beschreibungs-Funktion

- [ ] Es gibt genau **eine** Implementierung der Bildbeschreibung; Eingabe ist ein Dateipfad, Ausgabe ein Beschreibungstext (Schnittstelle wie heute `get_ai_description`)
- [ ] Der MQTT-Verarbeitungspfad (`alice/dms/image`) nutzt diese Funktion; EXIF- und GPS-Extraktion bleiben dort unverändert
- [ ] Die Beschreibung ist weiterhin deutsch, 3–5 Sätze pro (Gesamt-)Bild, max. 50.000 Zeichen (bestehendes Verhalten)
- [ ] Schlägt die Beschreibung fehl, liefert die Funktion einen Fehler (kein leerer oder Platzhalter-Text) — bestehendes Verhalten aus PROJ-99

### Standard-Format (Seitenverhältnis bis einschließlich 2:1 bzw. 1:2)

- [ ] Bilder, deren lange Seite höchstens doppelt so lang ist wie die kurze (Quer- **und** Hochformat), werden als **ein** Bild beschrieben
- [ ] Verkleinerung wie bisher: längste Seite auf 1024 px (Wert konfigurierbar, eine Regel für Einzelbilder und Teilbilder)
- [ ] Beispiel: 6000×4000 (3:2), 4000×6000 (2:3), 3840×2160 (16:9), 4000×2000 (2:1) → je ein LLM-Aufruf, Beschreibung wie bisher

### Nicht-Standard-Format (Seitenverhältnis über 2:1 bzw. 1:2) — Teilbild-Zerlegung

- [ ] Das Bild wird entlang der langen Seite in Teilbilder mit einem Seitenverhältnis von ca. **3:2** (hochkant: **2:3**) zerlegt; benachbarte Teilbilder überlappen um ca. **10 %**
- [ ] Es werden **höchstens 8 Teilbilder** erzeugt; würden mehr benötigt, werden die Teilbilder breiter (bei Hochformat: höher) bis maximal 2:1; reicht auch das nicht (Bild über ca. 16:1), werden trotzdem 8 Teilbilder erzeugt — kein Fehler
- [ ] Jedes Teilbild wird einzeln (verkleinert nach derselben 1024-px-Regel) an das Vision-Modell übergeben
- [ ] Reihenfolge der Teilbilder: links → rechts (Querformat) bzw. oben → unten (Hochformat)
- [ ] Anschließend erzeugt ein weiterer LLM-Aufruf aus den Teil-Beschreibungen **eine** zusammenhängende Gesamtbeschreibung, die das Bild als eine Szene beschreibt (keine Aufzählung „Teil 1 … Teil 8")
- [ ] Beispiel: 22704×1760 (Panorama, ≈12,9:1) → 8 Teilbilder + 1 Zusammenfassung → eine deutsche Beschreibung, die den Bildinhalt erkennbar wiedergibt
- [ ] Beispiel: 1760×22704 (senkrechtes Panorama) → analog, Zerlegung von oben nach unten

### Fehlerverhalten (alles oder nichts)

- [ ] Schlägt ein Teilbild-Aufruf oder die Zusammenfassung fehl (Timeout, HTTP-Fehler, leere Antwort), gilt die gesamte Beschreibung als fehlgeschlagen — es wird **nie** eine Teil-Beschreibung gespeichert
- [ ] Keine automatischen Wiederholungen innerhalb eines Aufrufs; Wiederholung übernimmt der Backfill beim nächsten Lauf
- [ ] Im MQTT-Pfad führt ein Fehler zu `extraction_failed=true` (bestehendes Verhalten)

### Pixel-Obergrenze

- [ ] Bilder bis einschließlich **250 Megapixel** werden verarbeitet (die Pillow-Standardgrenze von ca. 179 MP wird entsprechend angehoben; Wert konfigurierbar)
- [ ] Bilder über 250 MP werden nicht verarbeitet: `extraction_failed=true` und ein eindeutiger Log-Eintrag mit der Pixelzahl (z.B. „image too large: 312 MP")
- [ ] Beispiel: 16320×12240 (≈199,7 MP, 200-MP-Modus Oppo Find X9 Ultra) → wird normal beschrieben

### Backfill (`alice-dms-image-description-backfill`)

- [ ] Der Backfill übergibt pro Bild nur noch den aufgelösten Dateipfad an die zentrale Beschreibungs-Funktion und erhält Beschreibungstext oder Fehler zurück
- [ ] Der Backfill liest Bilddateien **nicht** mehr selbst ein und ruft das LLM **nicht** mehr selbst auf
- [ ] Erfolg: PATCH nach Weaviate wie bisher (`ai_description`, `extraction_failed=false`), Zählung `updated`
- [ ] Fehler: Bild bleibt `extraction_failed=true`, Zählung `still_failed`
- [ ] EXIF/GPS werden durch den Backfill nicht neu extrahiert
- [ ] Zeitfenster, Redis-Lock, Auto-Fortsetzung und Summary aus PROJ-96 bleiben funktional unverändert
- [ ] Das 52,8-MB-Panorama (22704×1760), das bisher HTTP 413 auslöste, wird vom Backfill erfolgreich beschrieben, ohne dass n8n abstürzt (PROJ-96 BUG-5 behoben)

## Edge Cases

- **Grenzfall exakt 2:1 bzw. 1:2** (z.B. 4000×2000): gilt als Standard-Format → Einzelbild.
- **Knapp darüber** (z.B. 4100×2000, 2,05:1): Teilbild-Zerlegung — ergibt 2 Teilbilder mit Überlappung.
- **Extremes Panorama** (z.B. 40000×1000, 40:1): 8 Teilbilder, jeweils deutlich breiter als 2:1; das Ergebnis darf qualitativ schlechter sein, aber es entsteht eine Beschreibung und kein Fehler.
- **Sehr kleines, aber extremes Bild** (z.B. 800×100, Banner/Grafik): wird ebenfalls zerlegt; Teilbilder werden nicht hochskaliert.
- **Bild über 250 MP**: abgelehnt mit `extraction_failed=true` + Log; der Backfill zählt es bei jedem Lauf erneut als `still_failed` (bewusst akzeptiert, sehr selten).
- **Teilbild 5 von 8 läuft in Timeout**: gesamte Beschreibung schlägt fehl, nichts wird gespeichert, Backfill versucht das ganze Bild später erneut.
- **Lange Laufzeit eines Panoramas** (bis zu 9 LLM-Aufrufe à ~30 s ≈ 4–5 min): Der Backfill-Zeit-Check greift wie bisher nur zwischen Bildern; ein begonnenes Panorama wird zu Ende verarbeitet, auch wenn das Zeitfenster dadurch um einige Minuten überschritten wird.
- **Datei zwischenzeitlich nicht mehr lesbar**: bestehendes Verhalten (Backfill: `still_failed`/`no_file`; MQTT-Pfad: `extraction_failed=true`).
- **Gleichzeitige Aufrufe** aus MQTT-Pfad und Backfill: beide nutzen dieselbe Funktion; die GPU-Reihenfolge regelt das LLM-Gateway (PROJ-111).

## Außerhalb des Scopes

- **Keine Nachbesserung bestehender Beschreibungen** im Code. Panoramen, die bisher mit 1024-px-Kante „erfolgreich" (aber unbrauchbar) beschrieben wurden, bleiben unverändert. Eine einmalige manuelle Prüfung kann im Nachhinein erfolgen; Treffer werden manuell auf `extraction_failed=true` gesetzt und dann automatisch vom Backfill neu beschrieben.
- Keine Neu-Extraktion von EXIF/GPS durch den Backfill.
- Keine Änderung an Zeitfenstern, Lock oder Selbstaufruf-Logik des Backfills (PROJ-96).
- Keine Speicherung von Bildbreite/-höhe in Weaviate.

## Technical Requirements (optional)

- Speicher: Dekodieren eines 250-MP-Bildes benötigt grob 750 MB RAM (RGB); das Container-Speicherlimit muss dafür ausgelegt sein (`/architecture`)
- Konfigurierbar: Verkleinerungskante (Default 1024 px), Pixel-Obergrenze (Default 250 MP); Schwelle 2:1, Teilbild-Verhältnis 3:2, Überlappung 10 % und max. 8 Teilbilder dürfen als Konstanten fest sein
- Architekturfrage entschieden (siehe Tech Design): zentrale Funktion bleibt im `dms-extractor-image`, zusätzlich mit synchroner interner Schnittstelle für den Backfill

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

Die Beschreibungs-Funktion bleibt im Container `dms-extractor-image` und bekommt eine zweite „Tür": Neben dem bestehenden MQTT-Eingang (`alice/dms/image`) nimmt der Container jetzt auch direkte Anfragen vom Backfill entgegen (Pfad rein, Beschreibungstext raus). Beide Türen führen in dieselbe Funktion. Es entsteht kein neuer Container.

```
Neues Bild im DMS                          Backfill (n8n, nachts)
      |                                            |
  MQTT alice/dms/image                    direkte Anfrage "Beschreibe /mnt/nas/..."
      |                                            |
      +------------------+------------------------+
                         v
             dms-extractor-image
             +-- Eingang A: MQTT (EXIF + GPS + Beschreibung, wie bisher)
             +-- Eingang B: interne Anfrage (nur Beschreibung)   <-- NEU
             +-- Sperre: immer nur ein Bild gleichzeitig         <-- NEU
             +-- Bildbeschreibung (zentral)
                   +-- Größe prüfen (> 250 MP -> Fehler)         <-- NEU
                   +-- Seitenverhältnis prüfen (<= 2:1 ?)        <-- NEU
                   |     +-- ja: 1 Bild (1024 px)  -> LLM
                   |     +-- nein: bis zu 8 Teilbilder -> LLM je Teilbild
                   |                + 1 Zusammenfassung -> LLM  <-- NEU
                   +-- alles oder nichts: Fehler statt Teilergebnis
                         v
                 LLM-Gateway (PROJ-111) -> llama-3090
```

### A) Komponenten-Struktur

```
dms-extractor-image (bestehender Container, erweitert)
+-- MQTT-Eingang (besteht)           -> EXIF, GPS, Geocode-Queue, Redis-Ergebnis
+-- Interner Anfrage-Eingang (NEU)   -> nur Beschreibung, Antwort direkt zurück
+-- Bild-Vorbereitung (NEU)
|   +-- Größenprüfung (Obergrenze 250 MP)
|   +-- Entscheidung Einzelbild / Teilbilder (Schwelle 2:1 bzw. 1:2)
|   +-- Zerlegung in max. 8 Teilbilder (3:2, 10 % Überlappung)
+-- Bildbeschreibung (besteht, erweitert)
|   +-- Beschreibung je Bild/Teilbild
|   +-- Zusammenfassung der Teil-Beschreibungen (NEU)
+-- Ein-Bild-gleichzeitig-Sperre (NEU)

alice-dms-image-description-backfill (n8n, vereinfacht)
+-- Holen der Bilder mit extraction_failed=true   (unverändert)
+-- Dateipfad auflösen                            (unverändert)
+-- Beschreibung anfordern                        (ersetzt "Code: Ollama Vision")
+-- Ergebnis nach Weaviate schreiben              (unverändert)
+-- Zeitfenster / Lock / Auto-Fortsetzung / Summary (unverändert, PROJ-96)
```

### B) Daten

Es kommen **keine neuen gespeicherten Daten** hinzu. Weder PostgreSQL noch Weaviate bekommen neue Felder (Bildbreite/-höhe werden bewusst nicht gespeichert).

- **Anfrage des Backfills:** der Dateipfad des Bildes.
- **Antwort bei Erfolg:** der deutsche Beschreibungstext.
- **Antwort bei Fehler:** ein Fehlergrund, damit der Backfill ihn ins Log schreiben kann. Mögliche Gründe: Bild zu groß (> 250 MP), Datei nicht lesbar bzw. kein gültiges Bild, Pfad ungültig, Vision-Modell fehlgeschlagen oder leer.
- **Ergebnis im DMS:** unverändert `ai_description` und `extraction_failed` am Weaviate-Objekt bzw. im Redis-Ergebnis des MQTT-Pfads.

### C) Tech-Entscheidungen (begründet)

1. **Funktion bleibt im `dms-extractor-image`, kein neuer Container.** Der Container hat bereits NAS-Zugriff, Bildbibliotheken inkl. HEIC und die LLM-Konfiguration. Ein neuer Container bräuchte alles noch einmal samt Deployment, für eine einzige Funktion. Nachteil: Wenn der Backfill ein Panorama beschreiben lässt, warten neu eintreffende MQTT-Bilder ein paar Minuten. Das ist unkritisch, weil DMS-Bildbeschreibung ohnehin keine Echtzeit-Anforderung hat.

2. **Direkte Anfrage statt MQTT für den Backfill.** Der Backfill braucht das Ergebnis sofort zurück, um zwischen `updated` und `still_failed` zu unterscheiden und das Ergebnis selbst zu speichern. MQTT liefert keine Antwort. So bleibt auch EXIF/GPS unberührt (Spec: keine Neu-Extraktion).

3. **Nur ein Bild gleichzeitig.** Eine Sperre im Container serialisiert MQTT- und Backfill-Aufträge. Das schützt den Arbeitsspeicher (ein 250-MP-Bild braucht beim Dekodieren ca. 750 MB) und passt zum LLM-Server, der ohnehin nur einen Slot hat (`n_slots = 1`). Die Reihenfolge zwischen Chat und DMS regelt weiterhin das LLM-Gateway (PROJ-111).

4. **Größe wird vor dem Dekodieren geprüft.** Aus dem Datei-Kopf liest man die Pixelmaße, ohne das Bild zu laden. Bilder über 250 MP werden sofort abgelehnt, bevor Speicher belegt wird. Pillows eigene Schutzgrenze (ca. 179 MP) wird auf die gleiche Obergrenze angehoben, sonst würden 200-MP-Bilder schon beim Öffnen scheitern.

5. **Zusammenfassung in einem eigenen LLM-Aufruf.** Die Teil-Beschreibungen werden dem Modell als reiner Text zurückgegeben mit der Anweisung, daraus eine zusammenhängende Szenenbeschreibung zu machen. Das braucht kein Bild und ist schnell. Die Sprache bleibt wie bei allen DMS-Beschreibungen Deutsch (PROJ-79: durchgängig deutsche DMS-Daten).

6. **Schutz der internen Anfrage.** Die Schnittstelle ist nur im internen Backend-Netz erreichbar und wird nicht über nginx veröffentlicht. Wie im MQTT-Pfad werden nur Pfade unter `/mnt/nas/` akzeptiert, damit darüber keine beliebigen Dateien gelesen werden können.

7. **MQTT-Verbindung gegen lange Verarbeitung absichern.** Die MQTT-Verarbeitung blockiert den Netzwerk-Thread des Clients; während eines mehrminütigen Panoramas kann er keine Keepalive-Signale senden (heute 300 s, der Broker trennt nach ca. 450 s). Lösung: Keepalive deutlich erhöhen (Richtwert 1800 s), sodass die längste realistische Verarbeitung (inkl. Wartezeit im Gateway) abgedeckt ist. Das ist die kleinere Änderung gegenüber einem Umbau auf einen Arbeits-Thread und erhält das bisherige Quittierungsverhalten (Nachricht gilt erst nach Verarbeitung als zugestellt).

8. **Gesundheitsprüfung bleibt wirksam.** Der Heartbeat des Containers läuft in einem eigenen Thread und wird durch lange Aufträge nicht ausgebremst. Ein Panorama führt daher nicht zu einem fälschlich „unhealthy" markierten Container.

9. **Container-Speicherlimit setzen.** Bisher gibt es keins. Richtwert 2 GB (ein Bild gleichzeitig, Dekodieren + Zuschnitt + Verkleinern). Der genaue Wert wird im `/backend` am echten 200-MP-Testbild verifiziert.

### D) Workflow-Architektur Backfill (n8n)

- **Trigger:** unverändert (Schedule 23:30 / 06:00, Webhook für Ad-hoc, Selbstaufruf).
- **Geänderter Schritt:** Der bisherige Knoten „Code: Ollama Vision" (liest Datei, Base64, LLM-Aufruf) wird ersetzt durch eine Anfrage an den Extractor mit dem bereits aufgelösten Dateipfad. n8n lädt nie mehr Bildinhalte → die Ursache für Heap-OOM und HTTP 413 entfällt.
- **Datenfluss:** Pfad → Extractor → Beschreibungstext oder Fehlergrund → bei Erfolg PATCH nach Weaviate (`ai_description`, `extraction_failed=false`) → Zähler `updated`; bei Fehler Zähler `still_failed` + Log mit Fehlergrund.
- **Timeout:** Die Anfrage muss länger warten dürfen als die längste Panorama-Verarbeitung (Richtwert 15 Minuten, deutlich mehr als die ca. 5 Minuten für 9 LLM-Aufrufe).
- **Integrationen:** Extractor (neu), Weaviate (unverändert). Der Backfill ruft das LLM nicht mehr selbst auf; die Variablen `OLLAMA_URL` / `OLLAMA_VISION_MODEL` werden im Workflow nicht mehr benötigt.
- **Fehlerbehandlung:** Jeder Fehler (inkl. Zeitüberschreitung der Anfrage, Extractor nicht erreichbar) zählt als `still_failed`; das Bild bleibt `extraction_failed=true` und wird beim nächsten Lauf erneut versucht. Ist der Extractor insgesamt nicht erreichbar, soll der Lauf nicht alle 50 Bilder einzeln durchprobieren (Fehler-Abbruch-Kriterium wird im `/backend` festgelegt).
- **Hinweis:** Die Änderung betrifft eine Workflow-Datei; Deployment erfolgt wie üblich durch den Nutzer („Deploy n8n-workflow alice-dms-image-description-backfill").

### E) Reihenfolge der Umsetzung (Empfehlung)

1. Extractor: Größenprüfung, Zerlegung, Zusammenfassung und interner Eingang; MQTT-Keepalive, Speicherlimit (testbar mit Panorama 22704×1760 und 200-MP-Bild).
2. Extractor deployen und die neue Schnittstelle manuell mit den Testbildern prüfen.
3. Backfill-Workflow umstellen und von Hand mit einem Panorama ausführen (Webhook, kurzes Zeitlimit).

### F) Abhängigkeiten (Pakete)

- Kleiner Webserver für den internen Eingang, passend zu den übrigen Alice-Diensten (FastAPI samt Server-Paket) — wird im `/backend` festgelegt.
- Keine neuen Bildbibliotheken (Pillow, pillow-heif bleiben).

### G) Betroffene Dateien

- `docker/compose/automations/dms-extractor-image/` (Funktion, Compose: internes Netz, Speicherlimit, Konfiguration der Obergrenzen)
- `workflows/alice-dms-image-description-backfill.json`
- Keine Änderung an `sql/`, Frontend oder nginx.

## Implementation Notes (Backend, 2026-10-14)

### `dms-extractor-image`
- **Zentrale Funktion** `get_ai_description(file_path)` (Name/Schnittstelle unverändert) wirft bei Fehler `DescriptionError` mit Grund `unreadable` | `too_large` | `vision_failed`; MQTT-Pfad und HTTP-Eingang nutzen dieselbe Funktion.
- **Interner Eingang** `POST /describe` `{"file_path": "..."}` auf Port **8012** (FastAPI/uvicorn, nur Netz `backend`, nicht über nginx). Antworten: `200 {"ai_description"}`, `400 invalid_path`, `422 unreadable|too_large`, `502 vision_failed` (jeweils `{"error", "detail"}`). Pfadprüfung per `realpath` (kein `../`-Ausbruch aus `/mnt/nas/`). Zusätzlich `GET /health`.
- **Sperre:** `threading.Lock` um die gesamte Beschreibung — MQTT- und HTTP-Aufträge laufen strikt nacheinander (lokal verifiziert).
- **Größenprüfung** aus dem Datei-Kopf vor dem Dekodieren; Pillow-Grenze deaktiviert (`MAX_IMAGE_PIXELS = None`), eigene Grenze `IMAGE_MAX_MEGAPIXELS` (Default 250). Log: `image too large: 312 MP`.
- **Teilbild-Zerlegung** `tile_boxes()`: > 2:1 → Teilbilder ~3:2 mit ≥ 10 % Überlappung, max. 8; bei mehr Bedarf werden die Teilbilder so verbreitert, dass 8 Stück mit 10 % Überlappung das Bild abdecken (überschreitet 2:1 ab ca. 14,6:1 — Spec „ca. 16:1"). Pro Teilbild ein Vision-Aufruf (Prompt nennt „Ausschnitt i von n"), danach ein reiner Text-Aufruf zur Zusammenfassung als eine Szene.
- **Speicher:** Das Gesamtbild wird vor dem Zuschnitt auf die Zielgröße verkleinert (JPEG: `draft()` dekodiert direkt verkleinert); RGBA→RGB nutzt nur den Alpha-Kanal. Gemessene Spitzen (lokal, ohne Swap): 200-MP-JPEG 78 MB, 55-MB-Panorama-JPEG 137 MB, 200-MP-HEIC 1,4 GB, 250-MP-RGB-PNG 1,07 GB, 250-MP-RGBA-PNG 2,0 GB → **`mem_limit: 3g`** (statt Richtwert 2 GB).
- **Abweichung/Fund:** libheif lehnte 200-MP-HEIC ab (Sicherheitsgrenze 512 MB Allokation — betraf auch den bisherigen Code). `pillow_heif.options.DISABLE_SECURITY_LIMITS = True`; die eigene 250-MP-Grenze ersetzt diesen Schutz.
- **MQTT:** `keepalive=1800`; Netzwerk-Schleife jetzt per `loop_start()` im Hintergrund-Thread, uvicorn im Haupt-Thread. Heartbeat-Thread unverändert.
- Neue Konfiguration (`.env.example`): `OLLAMA_MAX_IMAGE_PX` (1024), `IMAGE_MAX_MEGAPIXELS` (250). Neue Pakete: `fastapi`, `uvicorn`.

### `alice-dms-image-description-backfill`
- „Code: Ollama Vision" → **„Code: Request Description"**: `POST http://dms-extractor-image:8012/describe` mit aufgelöstem Pfad, Timeout 15 min; Fehlergrund wird geloggt. „IF: Ollama OK" → „IF: Description OK" (prüft `_ok`), „Code: Log Still Failed (Ollama Error)" → „… (Description Error)" (`reason: description_error`).
- **Abbruch-Kriterium Extractor nicht erreichbar:** Verbindungsfehler (`ECONNREFUSED`, `ENOTFOUND`, `EAI_AGAIN`, `EHOSTUNREACH`) setzen `extractor_unreachable` in den Static Data → Schleife endet nach dem aktuellen Bild (wie Zeitlimit), keine Selbst-Fortsetzung. Zurückgesetzt bei jedem Batch-Start. Zeitüberschreitung einer einzelnen Anfrage zählt nur als `still_failed`.
- `OLLAMA_URL`/`OLLAMA_VISION_MODEL`/`OLLAMA_API_KEY` werden vom Workflow nicht mehr genutzt.
- Hinweis (unverändert, PROJ-96): Lock-TTL 15 min wird nur pro Batch erneuert; ein Batch mit mehreren Panoramen kann länger dauern. Da sich die Zeitfenster (23:30 / 06:00) nicht überschneiden, ist das nur bei manuellen Webhook-Läufen relevant.

### Deployment-Reihenfolge
1. `dms-extractor-image` neu bauen und starten (`./scripts/sync-compose.sh`, dann Build/Up).
2. Danach: **Deploy n8n-workflow `alice-dms-image-description-backfill`**.

## QA Test Results

**Tested:** 2026-10-14
**Umgebung:** lokal per Docker — gebautes `dms-extractor-image`-Image (`mem_limit`/`--memory` 3 GB, ohne Swap), Mosquitto 2, Redis 7, Mock-LLM (OpenAI-kompatibel, protokolliert Bildgröße/Prompt je Aufruf, steuerbare Fehler/Leerantworten/Verzögerung). Backfill-Node „Code: Request Description" in Node 20 mit `$input`/`$getWorkflowStaticData`-Stubs gegen den Test-Extractor ausgeführt; alle Code-Nodes per `node --check`, Verbindungen strukturell geprüft.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Zentrale Beschreibungs-Funktion
- [x] Genau eine Implementierung (`get_ai_description`), Eingabe Pfad, Ausgabe Text; MQTT-Pfad und `POST /describe` nutzen sie
- [x] MQTT-Pfad: EXIF (Datum, Kamera), GPS und Geocode-Queue-Eintrag unverändert (JPEG mit GPS getestet)
- [x] Deutscher Prompt, 3–5 Sätze; Kürzung auf 50.000 Zeichen bei Einzelbild und Panorama (60.000-Zeichen-Antwort → 50.000)
- [x] Fehler statt Leer-/Platzhaltertext (leere LLM-Antwort → `502 vision_failed`)

#### AC-2: Standard-Format (≤ 2:1 / 1:2)
- [x] 6000×4000, 4000×6000, 4000×2000 (exakt 2:1), 16320×12240 → je **1** LLM-Aufruf
- [x] Verkleinerung auf längste Seite 1024 px (1024×683, 683×1024, 1024×512, 1024×768); `OLLAMA_MAX_IMAGE_PX` konfigurierbar

#### AC-3: Teilbild-Zerlegung (> 2:1 / 1:2)
- [x] 4100×2000 → 2 Teilbilder (3:2) + Zusammenfassung
- [x] 22704×1760 → 8 Teilbilder + 1 Zusammenfassung (9 Aufrufe), Teilbilder 1024×579
- [x] 1760×22704 → 8 Teilbilder (579×1024), Reihenfolge oben → unten, Zusammenfassungs-Prompt „von oben nach unten"
- [x] Max. 8 Teilbilder, ≥ 10 % Überlappung, ~3:2, ≤ 2:1 solange möglich, lückenlose Abdeckung, Reihenfolge links → rechts — Eigenschaftstest über 10.142 zufällige Nicht-Standard-Formate
- [x] Zusammenfassung als eigener Text-Aufruf mit Anweisung „eine Szene, keine Aufzählung"
- [ ] **Offen (nur live prüfbar):** inhaltliche Qualität der Gesamtbeschreibung mit dem echten Vision-Modell → beim `/deploy` prüfen

#### AC-4: Fehlerverhalten (alles oder nichts)
- [x] Fehler bei Teilbild 5 von 8 → Abbruch nach genau 5 Aufrufen, `502`, kein Teilergebnis
- [x] Fehler bei der Zusammenfassung (Aufruf 9) → `502`, kein Teilergebnis
- [x] LLM nicht erreichbar → `502 vision_failed`; keine Wiederholungen innerhalb eines Aufrufs
- [x] MQTT-Pfad: Fehler → `extraction_failed=true` im Redis-Ergebnis

#### AC-5: Pixel-Obergrenze
- [x] 200 MP JPEG (16320×12240) → beschrieben, Peak 78 MB
- [x] 200 MP HEIC → beschrieben, Peak 1,4 GB (vorher an libheif-Grenze gescheitert, siehe Implementation Notes)
- [x] 250 MP PNG (RGB/RGBA) → beschrieben, Peak 1,07 GB / 2,0 GB (< 3 GB Limit, kein OOM-Kill)
- [x] 312 MP → `too_large`, Log „image too large: 312 MP"; MQTT-Pfad `extraction_failed=true`

#### AC-6: Backfill
- [x] Übergibt nur den aufgelösten Pfad an `http://dms-extractor-image:8012/describe`, liest keine Bilddateien, ruft kein LLM mehr auf (keine `OLLAMA_*`-Referenzen mehr im Workflow)
- [x] Erfolg → `_ok=true` + Text → bestehender PATCH-Zweig (`ai_description`, `extraction_failed=false`, Zählung `updated`)
- [x] Fehler (422/502/Timeout) → `_ok=false` → `still_failed`, Fehlergrund im Log
- [x] Extractor nicht erreichbar → `extractor_unreachable` gesetzt → Schleife endet, keine Selbst-Fortsetzung
- [x] Zeitfenster, Lock, Auto-Fortsetzung, Summary: Nodes unverändert (nur Ergänzung des Abbruch-Flags)
- [x] 55,8-MB-Panorama (22704×1760, Rauschen, realistischer Dateigröße) → Extractor-Peak 137 MB; n8n erhält nur Text
- [ ] **Offen (nur live prüfbar):** das echte 52,8-MB-Panorama über den produktiven Backfill → beim `/deploy` prüfen
- [x] n8n Task-Runner-Timeout (`N8N_RUNNERS_TASK_TIMEOUT=3600`) liegt über dem 15-min-Request-Timeout

### Edge Cases Status
- [x] EC exakt 2:1 → Einzelbild; 2,05:1 → 2 Teilbilder
- [x] EC 40000×1000 → 8 Teilbilder (breiter als 2:1), Beschreibung entsteht, kein Fehler
- [x] EC 800×100 → 6 Teilbilder à 150×100, nicht hochskaliert
- [x] EC > 250 MP → abgelehnt + Log
- [x] EC Teilbild-Timeout/-Fehler → nichts gespeichert
- [x] EC Datei fehlt / Verzeichnis / keine Bilddatei / defektes Bild → `422 unreadable`
- [x] EC gleichzeitige Aufrufe MQTT + Backfill → strikt nacheinander (Aufruf-Reihenfolge L×8,S,V×8,S — nie verschachtelt)
- [x] Zusätzlich: Bild-Modi L, P, P+Transparenz, LA, 1-Bit, CMYK, I;16, RGBA → korrekt beschrieben
- [x] Zusätzlich: MQTT-Keepalive 1800 s beim Broker angekommen (`k1800`); Container stoppt sauber (0,5 s, Exit 0); Heartbeat läuft während Verarbeitung weiter

### Security Audit Results
- [x] Kein Port veröffentlicht, keine nginx-Route; nur im Docker-Netz `backend` erreichbar
- [x] Pfad-Validierung per `realpath`: `/etc/passwd`, `/mnt/nas/../etc/passwd`, `/mnt/nasty/…`, `/mnt/nas` und Symlink unter `/mnt/nas/` → `/etc/passwd` werden mit `400` abgelehnt
- [x] Fehlerhafte Payloads (leer, kein JSON, falscher Typ) → `422` (Pydantic), Container stabil
- [x] `/docs`, `/openapi.json` deaktiviert (404)
- [x] LLM-API-Key wird gesendet (`Bearer`), erscheint aber nicht in den Logs
- [x] Speicher: eigene 250-MP-Grenze greift vor dem Dekodieren (ersetzt Pillow-/libheif-Schutz), Sperre verhindert parallele Großbilder
- [x] BUG-1 (Low): Null-Byte im Pfad → `500` — **behoben 2026-10-14**, jetzt `400 invalid_path`
- Info (akzeptiert, Tech-Design-Entscheidung): Endpunkt ohne Authentifizierung — jeder Container im Netz `backend` kann Beschreibungen von NAS-Bildern anfordern bzw. die Warteschlange belegen

### Bugs Found

#### BUG-1: Null-Byte im `file_path` führt zu HTTP 500 — FIXED (2026-10-14)
- **Severity:** Low
- **Fix:** `describe()` lehnt Pfade mit `\x00` vor `realpath` mit `400 invalid_path` ab. Nachtest: Null-Byte-Pfade → 400; `../`-Ausbruch → 400; Panorama/Standardbild → 200 (keine Regression)
- **Steps to Reproduce:**
  1. `POST /describe` mit `{"file_path": "/mnt/nas/test/a\u0000b.jpg"}`
  2. Expected: `400 invalid_path`
  3. Actual: `500 Internal Server Error` (unbehandelter `ValueError` aus `os.path.realpath`); Container läuft weiter, Backfill würde `still_failed` zählen
- **Priority:** Nice to have (nur intern erreichbar, keine Auswirkung außer Statuscode)

#### INFO-1: 16-Bit-PNGs mit vollem Wertebereich werden weiß
- **Severity:** Info (keine Regression — identisches Verhalten mit dem bisherigen `convert("RGB")`)
- Pillow schneidet `I;16`-Werte > 255 beim Wandeln nach RGB ab. Außerhalb des Scopes; bei Bedarf eigenes Ticket.

### Regression
- PROJ-56/99 (MQTT-Extraktion): EXIF/GPS/Geocode-Queue/Redis-Ergebnis unverändert; Ablehnung ungültiger Pfade und ungültigen JSONs unverändert
- PROJ-111: Aufrufe gehen weiterhin mit eigenem Gateway-Key an `OLLAMA_URL`
- PROJ-96: Workflow-Struktur (Lock, Zeitfenster, Selbstaufruf, Summary) unverändert; alle Verbindungen konsistent

### Summary
- **Acceptance Criteria:** 29/31 bestanden lokal; 2 nur live prüfbar (Beschreibungsqualität mit echtem Modell, echtes 52,8-MB-Panorama über produktiven Backfill) → Teil des `/deploy`-Live-Tests
- **Bugs Found:** 1 total (0 critical, 0 high, 0 medium, 1 low — behoben) + 1 Info
- **Security:** Pass
- **Production Ready:** YES
- **Recommendation:** Deploy

## Deployment

**Deployed:** 2026-10-14
**Tag:** `v2.5.0-PROJ-112`

- `dms-extractor-image` neu gebaut und gestartet (interner Eingang `:8012`, `mem_limit: 3g`, MQTT-Keepalive 1800 s)
- n8n-Workflow `alice-dms-image-description-backfill` vom Nutzer deployed
- Live-Test durch den Nutzer: Container und Workflow arbeiten nach den Vorgaben

**Noch nicht live geprüft:** neu eingespulte Panorama-Bilder über den MQTT-Pfad. Ein gezielter Aufruf ist dafür nicht möglich; die Prüfung erfolgt, sobald ein Panorama im regulären Betrieb eintrifft (Beschreibungsqualität und Verhalten des Teilbild-Pfads mit dem echten Vision-Modell).
