# PROJ-76: DMS Bild-Backlog-Bereinigung

## Status: In Progress
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

### Component Overview

Vier unabhängige, kleine Änderungen an drei bestehenden Komponenten plus ein neuer Workflow. Kein neuer Container, keine neue HTTP-Schnittstelle.

```
alice-dms-processor (n8n, bestehend)
  └─ Node "MQTT: Publish Image Done"        ← GEÄNDERT: + inserted: true
         │ MQTT alice/dms/done
         ▼
alice-dms-thumbnailer (n8n, bestehend)      ← unverändert, ab jetzt korrekt getriggert
         │ HTTP POST /generate
         ▼
alice-dms-thumbnailer Container (Python)    ← GEÄNDERT: + tif/tiff (Pillow nativ), + heic (pillow-heif)


alice-dms-thumbnailer-backfill (n8n, bestehend)
  └─ Node "Code: Init Collections"          ← GEÄNDERT: COLLECTIONS += "Image"
         │ HTTP POST /generate (derselbe Container wie oben)
         ▼
alice-dms-thumbnailer Container


alice-dms-image-description-backfill (n8n, NEU)
  Webhook POST /image-description-backfill
         │
         ├─ Weaviate-Abfrage: Image-Objekte mit extraction_failed = true (Batch)
         ├─ pro Objekt: Bilddatei von NAS lesen (file_path, Fallback additionalPaths[0])
         ├─ Ollama Vision (gleicher Prompt/gleiches Modell wie dms-extractor-image)
         ├─ Erfolg → Weaviate PATCH (ai_description, extraction_failed: false)
         ├─ Fehlschlag → loggen, extraction_failed bleibt true, weiter zum nächsten Item
         └─ Abschluss-Log: { processed, updated, still_failed, remaining }
```

### Data Model (plain language)

Keine neuen Felder, keine Schemaänderung. Betroffen sind ausschließlich zwei bereits existierende Felder der Weaviate-Collection "Image":

- `ai_description` — wird im Beschreibungs-Backfill per PATCH überschrieben, wenn ein neuer Ollama-Vision-Aufruf erfolgreich war
- `extraction_failed` — wird von `true` auf `false` gesetzt, sobald `ai_description` erfolgreich nachgetragen wurde

Alle anderen Felder des Objekts (`weaviate_uuid`, EXIF-Felder, Geocoding-Felder, `thumbnail_path`, `additionalPaths`) werden von keinem der vier Fixes berührt.

### Tech Decisions

| Entscheidung | Wahl | Begründung |
| --- | --- | --- |
| Beschreibungs-Backfill: eigener Workflow statt Erweiterung von `alice-dms-thumbnailer-backfill` | Neuer Workflow `alice-dms-image-description-backfill` | Andere Filterkriterien (`extraction_failed`) und anderer Scope (nur Collection "Image") als der bestehende Thumbnail-Backfill (`thumbnail_path` über 7 Collections); getrennt zu halten vermeidet bedingte Verzweigungen in einem sonst einfachen Workflow — folgt demselben Muster wie die bestehende Trennung zwischen `alice-dms-thumbnailer` (Laufzeit) und `alice-dms-thumbnailer-backfill` (einmalig) |
| Bilddatei-Zugriff direkt aus n8n (Code-Node, `fs`) statt neuer HTTP-Endpunkt in `dms-extractor-image` | Direkter NAS-Lesezugriff aus n8n | Der n8n-Container hat bereits denselben schreibgeschützten NAS-Mount wie `dms-extractor-image` (`nas-volumes.yml`); `dms-extractor-image` ist bewusst rein MQTT-getrieben ohne HTTP-Server — ein neuer Endpunkt nur für diesen einmaligen Backfill wäre zusätzliche Angriffsfläche und Wartungsaufwand ohne Wiederverwendung |
| Ollama-Vision-Aufruf direkt aus n8n (HTTP-Request-Node) statt über `dms-extractor-image` | Direkter Ollama-Call aus dem neuen Workflow | Gleiches Muster wie bereits bestehende direkte Weaviate-Aufrufe aus `alice-dms-processor` (z. B. `Code: Process Image Item`, Geocode-Phase); kein neuer Container nötig |
| Update-Mechanismus | PATCH statt Re-Insert | Verhindert Überschreiben/Verlust von EXIF-, Geocoding- oder Thumbnail-Daten, die für dieses Objekt bereits korrekt gesetzt sind (analog zur bestehenden Geoapify-PATCH-Phase aus PROJ-56) |
| Batch-Verarbeitung mit Wiederaufnahme | `Split In Batches`, gleiches Muster wie `alice-dms-thumbnailer-backfill` | Bereits erprobtes, unterbrechbares Muster; der Filter `extraction_failed = true` schließt bereits erfolgreich nachbearbeitete Bilder bei einem erneuten Lauf automatisch aus — kein zusätzlicher Fortschritts-Zustand nötig |
| HEIC-Unterstützung im Thumbnailer | `pillow-heif`-Abhängigkeit ergänzen | Bereits produktiv erprobt in `dms-extractor-image`; kein neues Toolchain-Risiko |
| TIFF-Unterstützung im Thumbnailer | Nur Erweiterung der Format-Liste, keine neue Abhängigkeit | Pillow unterstützt TIFF nativ |

### Dependencies (packages to install)

- `pillow-heif` — HEIC-Support für `alice-dms-thumbnailer` (Python-Container), ergänzt zu `requirements.txt`

### Workflow Architecture — `alice-dms-image-description-backfill` (neu)

- **Trigger:** Webhook POST (manuell ausgelöst durch Admin, analog zu `alice-dms-thumbnailer-backfill`)
- **Nodes (High-Level, in Ablaufreihenfolge):**
  1. **Fetch Failed Batch** — Weaviate-Query auf Collection "Image", Filter `extraction_failed = true`, Batch-Limit
  2. **IF Batch Empty** — keine Treffer → Workflow endet regulär mit leerem Summary
  3. **Split In Batches** — Einzelverarbeitung pro Bild
  4. **Resolve File Path** — versucht `file_path`; existiert die Datei nicht, wird der erste Eintrag aus `additionalPaths` versucht
  5. **IF File Readable** — keine der Pfad-Optionen lesbar → Item als `still_failed` loggen, weiter zum nächsten
  6. **Call Ollama Vision** — gleicher Prompt/gleiches Modell wie `dms-extractor-image` (`OLLAMA_VISION_MODEL`)
  7. **IF Ollama OK** — Fehler/Timeout → Item als `still_failed` loggen, `extraction_failed` bleibt `true`, weiter zum nächsten
  8. **Update Weaviate (PATCH)** — aktualisiert nur `ai_description` und `extraction_failed: false` am bestehenden Objekt
  9. **Loop** — nächstes Item, bis Batch abgearbeitet
  10. **Summary** — `{ processed, updated, still_failed, remaining }` im Execution Log

- **Data Flow:**

  ```
  Weaviate (Image, extraction_failed=true)
       ↓ Batch-Query
  NAS (file_path / additionalPaths, read-only)
       ↓ Bilddatei
  Ollama Vision (/api/generate)
       ↓ ai_description
  Weaviate PATCH (ai_description, extraction_failed: false)
  ```

- **Integrations:** Weaviate (Query + PATCH), NAS-Dateisystem (read-only, gleicher Mount wie `dms-extractor-image`), Ollama (Vision-Modell, gleiche Konfiguration wie `dms-extractor-image`: `OLLAMA_URL`, `OLLAMA_VISION_MODEL`)
- **Error Handling:**
  - Datei nicht lesbar (weder `file_path` noch `additionalPaths`) → Item bleibt `extraction_failed = true`, geloggt, kein Abbruch des gesamten Laufs
  - Ollama nicht erreichbar/Timeout → Item bleibt `extraction_failed = true`, geloggt, kein Abbruch des gesamten Laufs (nächster manueller Lauf versucht es erneut)
  - Kein Konflikt mit dem nächtlichen `alice-dms-processor` (inkl. PROJ-72-Lock) — der Backfill berührt weder die Redis-Listen `alice:dms:image`/`alice:dms:geocode_pending` noch den Processor-Lock, sondern ausschließlich bereits abgeschlossene Weaviate-Objekte

## Implementation Notes (Backend)

Alle vier Fixes wie im Tech Design entworfen umgesetzt:

1. **Trigger-Fix**: `workflows/alice-dms-processor.json`, Node `MQTT: Publish Image Done` — `inserted: true` in die MQTT-Payload aufgenommen.
2. **TIFF/HEIC-Support**: `docker/compose/automations/alice-dms-thumbnailer/` — `pillow-heif` zu `requirements.txt` hinzugefügt, `libheif1` im Dockerfile installiert (analog zu `dms-extractor-image`), `generate_thumbnail()` um `tif`/`tiff`/`heic` erweitert, HEIC-Opener beim Modul-Import registriert.
3. **Thumbnail-Backfill-Erweiterung**: `workflows/alice-dms-thumbnailer-backfill.json` — `"Image"` zur `COLLECTIONS`-Liste hinzugefügt. **Abweichung vom Tech Design (Bugfix während der Implementierung)**: Die Collection "Image" verwendet in Weaviate snake_case-Feldnamen (`file_path`, `file_hash`), während die anderen 7 Collections camelCase (`filePath`, `fileHash`) verwenden. Der bestehende Query-Node `Code: Query Weaviate (no thumbnail)` hatte die Feldnamen hartkodiert (`filePath fileHash`) — ein reines Hinzufügen von "Image" zur Liste hätte für diese Collection einen GraphQL-Fehler verursacht (Feld nicht gefunden) und dadurch 0 Ergebnisse geliefert. Der Query-Node wurde so angepasst, dass er je Collection die korrekten Feldnamen wählt (`isImage ? 'file_path' : 'filePath'`, analog für `fileHash`/`file_hash`).
4. **Neuer Beschreibungs-Backfill**: `workflows/alice-dms-image-description-backfill.json` (neu) — Webhook-Trigger, Batch-Fetch (Weaviate GraphQL, `extraction_failed = true`, Limit 50 pro Lauf), pro Bild: Pfadauflösung (`file_path` → `additionalPaths`-Fallback) über direkten NAS-Lesezugriff (`fs`, gleicher Mount wie `dms-extractor-image`), Ollama-Vision-Aufruf (gleicher Prompt/gleiches Modell), bei Erfolg PATCH auf `ai_description`/`extraction_failed`. Zusammenfassung `{ processed, updated, still_failed, remaining }` wird geloggt und als Webhook-Response zurückgegeben; `remaining` wird per separater Weaviate-Aggregate-Query nach Lauf-Ende ermittelt (Anzahl noch offener `extraction_failed = true`-Objekte, unabhängig vom eigenen Batch-Limit). Neue Env-Var `OLLAMA_VISION_MODEL` zum n8n-Container hinzugefügt (`docker/compose/automations/n8n/compose.yml`, `.env.example`, `.env`), Wert identisch zu `dms-extractor-image`.

Keine Frontend-Änderungen (kein UI-Element für den neuen Backfill, wie im Spec gefordert).

## Deployment
_To be added by /deploy_
