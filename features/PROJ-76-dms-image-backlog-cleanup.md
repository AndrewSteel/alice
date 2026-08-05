# PROJ-76: DMS Bild-Backlog-Bereinigung

## Status: Planned
**Created:** 2026-08-05
**Last Updated:** 2026-08-05

## Dependencies
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — betrifft den bestehenden `alice-dms-thumbnailer`-Workflow, den `alice-dms-thumbnailer`-Container und den bestehenden `alice-dms-thumbnailer-backfill`-Workflow
- Requires: PROJ-56 (DMS Bildanalyse) — betrifft `dms-extractor-image`, `alice-dms-processor` (Bild-Teilworkflow) und die Weaviate-Collection "Image"

## Overview

Nach Produktiveinsatz von PROJ-55 und PROJ-56 wurden drei zusammenhängende Mängel festgestellt, die alle die Bildverarbeitung im DMS betreffen:

1. **Thumbnails wurden nie für Bilder erzeugt.** Der Node `MQTT: Publish Image Done` in `alice-dms-processor` (Bild-Teilworkflow) setzt kein `inserted`-Feld in der MQTT-Payload, während `alice-dms-thumbnailer` jede Nachricht ohne `inserted = true` stillschweigend verwirft. Dies betrifft alle Bilder seit Deployment von PROJ-56, nicht nur den aktuellen Backlog.
2. **TIFF und HEIC erzeugen auch nach Fix Nr. 1 kein Thumbnail.** `alice-dms-thumbnailer` unterstützt aktuell nur `jpg, jpeg, png, webp, gif, bmp` — beides von PROJ-56 unterstützte Bildformate (`tif`/`tiff`, `heic`) fehlen.
3. **Ein Teil der bereits im DMS vorhandenen Bilder hat keine KI-Beschreibung**, weil `OLLAMA_URL` in der `.env` von `dms-extractor-image` zeitweise falsch gesetzt war. Diese Bilder wurden gemäß bestehendem Fehlerpfad trotzdem mit `extraction_failed: true` und leerer `ai_description` in Weaviate eingefügt (kein Datenverlust, aber unvollständig).

Dieses Feature bündelt die Behebung aller drei Mängel: den Trigger-Fix (rückwirkungsfrei für künftige Bilder), die fehlenden Thumbnail-Formate, einen erweiterten Thumbnail-Backfill (damit bereits vorhandene Bilder ohne Thumbnail rückwirkend eins erhalten) und einen neuen, gezielten Backfill für fehlende Bildbeschreibungen.

## User Stories

- Als Andreas möchte ich, dass für jedes neu importierte Bild automatisch ein Thumbnail erzeugt wird, damit es in der Flip-Card-Ansicht (PROJ-54/PROJ-75) mit Vorschaubild statt Platzhalter erscheint.
- Als Andreas möchte ich, dass auch TIFF- und HEIC-Bilder ein Thumbnail erhalten, damit alle von PROJ-56 unterstützten Bildformate in der Flip-Card-Ansicht vollständig nutzbar sind.
- Als Admin möchte ich einen Backfill anstoßen können, der für bereits vorhandene Bilder ohne Thumbnail dieses nachträglich erzeugt, ohne bestehende Daten zu verändern.
- Als Admin möchte ich einen separaten Backfill anstoßen können, der für Bilder mit `extraction_failed = true` die KI-Beschreibung nachträglich erzeugt, damit der durch die fehlerhafte `.env` entstandene Backlog bereinigt wird — ohne bereits erfolgreich ermittelte EXIF-/GPS-/Geocoding-Daten zu verwerfen oder erneut zu verbrauchen (z. B. Geoapify-Tageslimit).

## Acceptance Criteria

### 1. Thumbnail-Trigger-Fix (`alice-dms-processor`)

- [ ] Node `MQTT: Publish Image Done` nimmt zusätzlich `inserted: true` in die Nachricht auf (analog zu `inserted: $json._weaviate_inserted` im bestehenden Dokumenten-Pfad `MQTT: Publish Done`)
- [ ] Da dieser Node ausschließlich im Zweig `IF: Image Is New` (`_image_action === 'new'`) feuert, ist `inserted: true` für jede darüber gesendete Nachricht korrekt — das Bild wurde zu diesem Zeitpunkt bereits erfolgreich in Weaviate eingefügt
- [ ] Der Dedup-Pfad (`_image_action === 'add_path'`, bestehendes Bild unter neuem Pfad) löst weiterhin **keine** `alice/dms/done`-Nachricht aus (unverändertes Verhalten)
- [ ] Nach dem Fix erzeugt `alice-dms-thumbnailer` für jedes neu eingefügte Bild automatisch ein Thumbnail, ohne dass an `alice-dms-thumbnailer` selbst etwas geändert werden muss

### 2. Thumbnail-Formatunterstützung (`alice-dms-thumbnailer`)

- [ ] `generate_thumbnail()` unterstützt zusätzlich `tif`/`tiff` (Pillow öffnet TIFF nativ; zentrierter Zuschnitt wie bei JPG/PNG/WEBP)
- [ ] `generate_thumbnail()` unterstützt zusätzlich `heic` (neue Abhängigkeit `pillow-heif`, registriert analog zu `dms-extractor-image`; zentrierter Zuschnitt)
- [ ] Bestehende Formate (`jpg, jpeg, png, webp, gif, bmp`) bleiben unverändert unterstützt
- [ ] Fehlschlag bei defekter/korrupter Bilddatei verhält sich wie bisher (Fehler geloggt, `422`, Platzhalter im Frontend) — kein neues Fehlerverhalten

### 3. Thumbnail-Backfill-Erweiterung (`alice-dms-thumbnailer-backfill`)

- [ ] `Code: Init Collections` nimmt `"Image"` in die `COLLECTIONS`-Liste auf
- [ ] Backfill erzeugt Thumbnails für alle vorhandenen Image-Objekte ohne `thumbnail_path`, unabhängig vom Wert von `extraction_failed` oder `ai_description` — Thumbnail-Erzeugung hängt nur von `file_path`/`file_type` ab, nicht von der Bildbeschreibung
- [ ] Bestehendes Verhalten für die anderen 7 Collections (Invoice, BankStatement, BankTransaction, Document, Email, SecuritySettlement, Contract) bleibt unverändert
- [ ] Bestehendes Progress-Log-Format (`{ processed, failed, skipped_already_has_thumb, remaining }`) gilt unverändert auch für die Collection "Image"

### 4. Beschreibungs-Backfill (neuer Workflow)

- [ ] Neuer, manuell auslösbarer n8n-Workflow (Webhook POST, analog zu `alice-dms-thumbnailer-backfill`) sucht Weaviate-"Image"-Objekte mit `extraction_failed = true`
- [ ] Pro Treffer wird die Bilddatei erneut vom NAS gelesen: zunächst über `file_path`; ist diese Datei nicht mehr vorhanden, wird der erste Eintrag aus `additionalPaths` versucht
- [ ] Nur der KI-Beschreibungsschritt wird wiederholt (Ollama Vision, gleicher Prompt und gleiches Modell wie in `dms-extractor-image`) — EXIF-, GPS- und bereits vorhandene Geocoding-Felder (`country`, `country_code`, `city`, `district`) werden **nicht** erneut ermittelt oder verändert
- [ ] Bei Erfolg: Weaviate-Objekt wird per PATCH aktualisiert mit neuer `ai_description` und `extraction_failed = false`; `weaviate_uuid`, `thumbnail_path`, `additionalPaths`, EXIF- und Geo-Felder bleiben unverändert
- [ ] Bei erneutem Fehlschlag (Datei nicht mehr vorhanden, Ollama nicht erreichbar): `extraction_failed` bleibt `true`, kein PATCH, Fehler wird geloggt
- [ ] Verarbeitung erfolgt in Batches; der Workflow kann jederzeit erneut gestartet werden, ohne bereits erfolgreich nachbearbeitete Bilder erneut zu verarbeiten (Filter `extraction_failed = true` schließt sie automatisch aus — kein Duplikat-Risiko)
- [ ] Nach Abschluss (oder Abbruch, z. B. Ollama zwischenzeitlich nicht erreichbar) wird ein Zusammenfassungs-Log ausgegeben: `{ processed, updated, still_failed, remaining }`
- [ ] Kein UI-Element — Auslösung erfolgt manuell per Webhook-Call (Postman/curl), analog zu PROJ-55

## Edge Cases

- **Bild-Datei nicht mehr unter `file_path` vorhanden**: Beschreibungs-Backfill versucht die Pfade aus `additionalPaths`; sind alle Pfade ungültig, bleibt `extraction_failed = true`, Fehler wird geloggt, kein Datenverlust (Objekt bleibt wie vorher)
- **Ollama während des Beschreibungs-Backfill-Laufs nicht erreichbar**: Betroffene Einträge bleiben `extraction_failed = true`, werden im Summary als `still_failed` gezählt, nächster manueller Lauf versucht sie erneut
- **Bild wurde bereits vor diesem Fix korrekt beschrieben** (`extraction_failed = false`): wird vom Backfill-Filter nicht erfasst, keine erneute Verarbeitung, keine unnötigen Ollama-Aufrufe
- **Gleichzeitiger Lauf des nächtlichen `alice-dms-processor` (Insert-/Geocode-Phasen, inkl. PROJ-72-Lock) und des Beschreibungs-Backfills**: kein Konflikt, da der Backfill nur bereits vorhandene Weaviate-Objekte per PATCH auf `ai_description`/`extraction_failed` aktualisiert und weder die Redis-Listen `alice:dms:image`/`alice:dms:geocode_pending` noch den Processor-Lock berührt
- **HEIC-Datei, die auch pillow-heif nicht öffnen kann**: Thumbnail-Generierung schlägt fehl wie bei jedem anderen Konvertierungsfehler (Platzhalter im Frontend, Fehler geloggt, kein Absturz des Containers)
- **Sehr großer Backlog** (mehrere hundert Bilder mit `extraction_failed = true`): Batch-Verarbeitung im Beschreibungs-Backfill erlaubt Unterbrechung und Wiederaufnahme ohne doppelte Ollama-Aufrufe
- **Bild mit bereits gesetztem `thumbnail_path`, das erneut im (erweiterten) Thumbnail-Backfill auftaucht**: wird wie bei den anderen Collections übersprungen (`skipped_already_has_thumb`), kein erneutes Rendering
- **Bild mit `extraction_failed = true`, dessen Thumbnail aber bereits vorhanden ist** (z. B. weil Bild-Datei lesbar war, nur Ollama-Call scheiterte): Thumbnail- und Beschreibungs-Backfill sind unabhängig — Thumbnail-Backfill überspringt es (`thumbnail_path` bereits gesetzt), Beschreibungs-Backfill verarbeitet es trotzdem (eigener Filter auf `extraction_failed`)

## Technical Requirements

- **`alice-dms-thumbnailer`**: neue Abhängigkeit `pillow-heif` in `requirements.txt` (bereits erprobt in `dms-extractor-image`)
- **Neuer Beschreibungs-Backfill-Workflow**: nutzt dieselbe Ollama-Vision-Konfiguration wie `dms-extractor-image` (`OLLAMA_URL`, `OLLAMA_VISION_MODEL`), liest NAS read-only über denselben Mount
- **Kein Weaviate-Schema-Wechsel**: keine neuen Felder, nur PATCH auf bestehende Felder `ai_description`, `extraction_failed`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
