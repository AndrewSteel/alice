# PROJ-76: DMS Bild-Backlog-Bereinigung

## Status: Deployed
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

---

## QA Test Results

**Tested:** 2026-08-05
**Environment:** No live/VPN-connected n8n, Weaviate, Ollama or NAS mount available in this dev sandbox (production is VPN-only per CLAUDE.md). Testing methodology: real local execution of the Python container logic (actual Pillow/pillow-heif, real TIFF/HEIC files), faithful Node.js execution of every n8n Code node's JS body against mocked n8n globals (`$input`, `$(...)`, `$getWorkflowStaticData`, `axios`), n8n-mcp schema/connection validation, and full connection-graph/source review for every changed node. No workflow was deployed or triggered against the live n8n instance (`https://n8n.happy-mining.de`), consistent with the project rule that deployment is a manual, user-initiated step.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Thumbnail-Trigger-Fix (`alice-dms-processor`)
- [x] `MQTT: Publish Image Done` includes `inserted: true` in the payload (verified in diff and by reading the final node JSON)
- [x] Confirmed via connection-graph inspection: `IF: Image Is New` (`_image_action === 'new'`) output 0 (true) is the *only* path into `MQTT: Publish Image Done`
- [x] Confirmed the dedup path (`IF: Image Is New` output 1 / false, `_image_action === 'add_path'`) routes to `Split: Image Batches` instead — no `alice/dms/done` message, unchanged
- [x] Confirmed root cause end-to-end: `alice-dms-thumbnailer`'s `Code: Parse & Filter` node does `if (!msg.inserted) { ...; return []; }` — before this fix `msg.inserted` was always `undefined` (falsy), so **every** image silently skipped thumbnail generation since PROJ-56 shipped. After the fix `inserted: true` passes the filter with zero changes needed to `alice-dms-thumbnailer` itself.

#### AC-2: Thumbnail-Formatunterstützung (`alice-dms-thumbnailer`)
- [x] `tif`/`tiff`: real Pillow test (800×600 RGB TIFF) → thumbnail generated, 400×400 RGB, both lowercase and uppercase `file_type` values handled correctly
- [x] `heic`: real HEIC test file encoded via `pillow-heif` in an isolated venv, fed through the actual `generate_thumbnail()` → 400×400 RGB thumbnail generated successfully
- [x] Existing formats (`jpg`, `png` spot-checked) unaffected — no regression
- [x] Corrupt/undecodable TIFF and HEIC files both return `None` (existing 422 + placeholder error path unchanged, no new exception type introduced)

#### AC-3: Thumbnail-Backfill-Erweiterung (`alice-dms-thumbnailer-backfill`)
- [x] `"Image"` added to `COLLECTIONS` in `Code: Init Collections`
- [x] **Bug caught and fixed during implementation** (see Implementation Notes): the query node hardcoded camelCase field names (`filePath`/`fileHash`); Image uses snake_case (`file_path`/`file_hash`) in its Weaviate schema. Verified via mocked-axios test: without the per-collection field fix, an "Image" query would return a GraphQL field-not-found error → 0 results, silently defeating the backfill for all images. With the fix, a mixed `['Invoice', 'Image']` run correctly sends `filePath fileHash` for Invoice and `file_path file_hash` for Image, and correctly extracts `file_path` for each.
- [x] Docs without `thumbnail_path` still correctly filtered per-collection (verified: an Image doc with `thumbnail_path` already set was correctly excluded from results in the mock test)
- [x] Other 7 collections unchanged — verified Invoice still queries/extracts via camelCase, unaffected by the Image-specific branch
- [ ] BUG (Low, pre-existing, not introduced by this change): the workflow's sticky-note documentation already claimed a progress-log format (`skipped_already_has_thumb`, `remaining`) that doesn't match the actual `Code: Summary` output fields (`skipped_no_path`, `total`). This drift predates PROJ-76; only the collection list in that same sticky note was updated. Documented here for visibility, not blocking.

#### AC-4: Beschreibungs-Backfill (neuer Workflow)
- [x] New webhook-triggered workflow `alice-dms-image-description-backfill` created, POST-triggered, analogous structure to `alice-dms-thumbnailer-backfill`
- [x] Fetches Image objects with `extraction_failed = true` (GraphQL, batch limit 50/run) — verified via mocked axios (results mapping, empty-result sentinel, GraphQL-error and network-error graceful degradation all tested)
- [x] Path resolution tested for all 4 combinations: primary path exists; primary missing + `additionalPaths[0]` exists; all paths missing (graceful `_read_ok: false`, no crash); `file_path` null with only `additionalPaths` present
- [x] Only the Ollama Vision step is repeated — verified via code review: PATCH body only ever contains `{ ai_description, extraction_failed }`, nothing else is read or touched
- [x] On success: PATCH with new `ai_description` and `extraction_failed: false` — verified via mocked HTTP-status branch test (2xx → `updated`, non-2xx → `still_failed`)
- [x] On repeated failure (no file / Ollama unreachable / PATCH failure): no PATCH sent, `extraction_failed` stays `true`, error logged, run continues to next item — verified all three failure branches independently
- [x] Batch processing with safe resumption — verified: `extraction_failed = true` filter naturally excludes already-fixed images on the next invocation; no duplicate Ollama calls possible across runs
- [x] Summary `{ processed, updated, still_failed, remaining }` — exact field names verified via direct execution of the summary logic (both successful and failed remaining-count-query paths tested); `weaviate_uuid`, `thumbnail_path`, `additionalPaths`, EXIF/geo fields never touched (PATCH scope verified)
- [x] No UI element — confirmed, zero frontend files changed
- [ ] BUG (Low): if the *initial* Weaviate query itself fails (e.g. Weaviate briefly unreachable), the workflow reports the same `{processed:0, updated:0, still_failed:0, remaining:0}` summary as a genuine "nothing left to do" result — indistinguishable from the response alone (the underlying `console.warn` is visible in the n8n execution log, so it's not silent, just not surfaced in the HTTP response). This mirrors the exact same non-distinguishing behavior already present in the sibling `alice-dms-thumbnailer-backfill` query node, so it's a consistent (if imperfect) convention, not a new regression.
- [ ] BUG (Low): if the final "remaining" Aggregate query fails, `remaining` is reported as `null` rather than a number. Reasonable degrade-gracefully behavior; spec doesn't define expected behavior for this specific failure mode.

### Edge Cases Status

- [x] Bild-Datei nicht mehr unter `file_path` — additionalPaths fallback tested, graceful `extraction_failed = true` retained
- [x] Ollama nicht erreichbar während Backfill-Lauf — tested via IF: Ollama OK false-branch, item logged `still_failed`, run continues
- [x] Bereits korrekt beschriebenes Bild (`extraction_failed = false`) — excluded by the GraphQL filter itself, not re-processed
- [x] Gleichzeitiger Lauf von `alice-dms-processor` und Beschreibungs-Backfill — verified via code review: the new workflow touches neither the Redis lists (`alice:dms:image`, `alice:dms:geocode_pending`) nor the PROJ-72 processor lock; PATCH scope is disjoint from the geocode phase's PATCH fields (`country`/`city`/`district`/`country_code`)
- [x] HEIC-Datei, die pillow-heif nicht öffnen kann — tested with a corrupt `.heic` file, returns `None` gracefully, no crash
- [x] Sehr großer Backlog — batch limit (50/run) + `extraction_failed` filter allows safe interruption/resumption without duplicate Ollama calls
- [x] Bild mit `thumbnail_path` bereits gesetzt, erneut im Thumbnail-Backfill — `skipped_already_has_thumb` behavior unchanged, verified for Image collection specifically
- [x] Bild mit `extraction_failed = true`, Thumbnail aber bereits vorhanden — the two backfills are independent by design (different Weaviate filters), confirmed via code review

### Security Audit Results

**n8n workflow features:**
- [x] No secrets in code, logs, or HTTP responses — env vars referenced via `$env`, never echoed back
- [x] No path-traversal risk from the webhook caller: file paths read by `Code: Resolve & Read Image` originate only from Weaviate query results (previously written by `dms-extractor-image` after its own `/mnt/nas/` prefix validation), never from the webhook request body — the caller cannot influence which file is read
- [x] PATCH-only update strategy prevents accidental data loss/overwrite of EXIF, geocoding, thumbnail, or path fields
- [ ] NOTE (informational, not a new issue): the new webhook has `authentication: "none"`, identical to the existing `alice-dms-thumbnailer-backfill` webhook. Both rely on network-level trust (VPN + internal `/api/webhook/` routing) rather than app-level auth. Consistent with established convention for this class of admin-triggered backfill workflow — not a regression, but noting it since it's a new attack surface addition of the same class.

### Bugs Found

No Critical or High bugs. Three Low-severity items, all documented above:
1. Pre-existing sticky-note doc drift in `alice-dms-thumbnailer-backfill` (not introduced by PROJ-76)
2. New workflow can't distinguish "genuinely empty backlog" from "initial Weaviate query failed" in its HTTP response (matches existing sibling-workflow convention)
3. `remaining` reports `null` instead of a number if the final count query fails

None block deployment; all are candidates for a future polish pass if desired.

### Summary
- **Acceptance Criteria:** 4/4 passed (with 3 Low-severity notes, no Critical/High)
- **Bugs Found:** 3 total (0 critical, 0 high, 0 medium, 3 low)
- **Security:** Pass (no new attack surface beyond the established webhook-trust convention already used by the sibling backfill workflow)
- **Production Ready:** YES
- **Recommendation:** Deploy

## Deployment

**Deployed:** 2026-08-08
**n8n instance:** https://n8n.happy-mining.de

Deployed artifacts:
- `workflows/alice-dms-processor.json` — re-imported/activated (Image sub-workflow `MQTT: Publish Image Done` now sends `inserted: true`)
- `workflows/alice-dms-thumbnailer-backfill.json` — re-imported/activated (Image collection included, per-collection field-name fix)
- `workflows/alice-dms-image-description-backfill.json` — new workflow imported and activated (webhook `POST /webhook/alice-dms-image-description-backfill`)
- `alice-dms-thumbnailer` container — rebuilt with `pillow-heif` + `libheif1` for TIFF/HEIC support, and `OLLAMA_VISION_MODEL` env var added to the `n8n` container

No frontend changes were part of this feature.

Confirmed by user: workflows deployed and operating as expected in production.
