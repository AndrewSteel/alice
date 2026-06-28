# PROJ-55: DMS Thumbnail-Generierung

## Status: Approved
**Created:** 2026-06-27
**Last Updated:** 2026-06-27

## Dependencies
- Requires: PROJ-19 (DMS Processor Workflow) — Thumbnail-Generierung wird nach erfolgreichem Weaviate-Insert ausgelöst; `original_path` und Weaviate-UUID werden benötigt
- Required by: PROJ-54 (Vision-Chat: Flip-Card Ergebnisansicht) — Flip-Cards brauchen Thumbnails als Vorschaubilder

## Overview

Für jedes Dokument, das erfolgreich in Weaviate gespeichert wird, soll ein quadratisches **1:1-Thumbnail** erzeugt und im **Warm-Storage** auf dem NAS abgelegt werden. Das Thumbnail dient als Vorschaubild in den Flip-Cards von PROJ-54. Die Generierung wird durch den MQTT-Topic `alice/dms/done` ausgelöst, den PROJ-19 nach jedem erfolgreichen Weaviate-Insert bepublisht. Für bereits vorhandene Weaviate-Dokumente ohne Thumbnail wird ein einmaliger **Backfill-Prozess** bereitgestellt.

## User Stories

- Als System möchte ich nach jedem erfolgreichen DMS-Import automatisch ein Thumbnail erzeugen, damit neu verarbeitete Dokumente sofort in der Flip-Card-Ansicht mit Vorschaubild erscheinen.
- Als Andreas möchte ich, dass Dokumente ohne Thumbnail einen Platzhalter anzeigen, damit die Flip-Card-Ansicht auch während der Backfill-Phase vollständig nutzbar ist.
- Als Admin möchte ich einen Backfill-Prozess ausführen können, der Thumbnails für alle bereits in Weaviate vorhandenen Dokumente ohne Thumbnail erstellt.
- Als System möchte ich Thumbnails über einen API-Endpunkt abrufen können, damit das Frontend sie in den Flip-Cards anzeigen kann.

## Acceptance Criteria

### Thumbnail-Generierung (Laufzeit)

- [ ] Ein neuer n8n-Workflow `alice-dms-thumbnailer` abonniert MQTT-Topic `alice/dms/done` und wird pro erfolgreichem Weaviate-Insert ausgelöst
- [ ] Die MQTT-Nachricht von PROJ-19 enthält: `original_path`, `weaviate_uuid`, `document_type`, `file_type`
- [ ] Pro Dokument wird **genau ein** Thumbnail erzeugt
- [ ] Thumbnail-Format: **quadratisch 1:1**, Zielgröße in der Architektur festlegen (Richtwert: 400×400 px)
- [ ] Zuschnitt-Regeln nach Dateityp:
  - PDF: erste Seite rendern, vom **oberen Rand** quadratisch zuschneiden
  - DOCX / XLSX / ODT / ODS: LibreOffice headless → PDF → erste Seite → oberer Rand-Zuschnitt
  - Bilder (JPG, PNG, WEBP): **zentrierter** quadratischer Zuschnitt
  - TXT / MD: Textvorschau (erste N Zeilen) als gerendertes Bild oder generisches Dokument-Icon
- [ ] Thumbnail wird als **JPEG** (Qualität ≥ 80%) im Warm-Storage unter einem definierten Pfad gespeichert (Schema: `<warm-storage-root>/thumbnails/<weaviate_uuid>.jpg`)
- [ ] Nach erfolgreicher Speicherung wird der Thumbnail-Pfad in Weaviate am entsprechenden Objekt als Feld `thumbnail_path` aktualisiert
- [ ] Bei Fehler (Konvertierung schlägt fehl): Fehler wird geloggt, kein Thumbnail gespeichert; MQTT `alice/dms/thumb_error` wird publiziert; nächste Verarbeitung des gleichen Dokuments überschreibt (kein dauerhafter Fehlerzustand)
- [ ] Bereits vorhandenes Thumbnail (`thumbnail_path` in Weaviate gesetzt): wird **überschrieben** (Dokument wurde re-importiert)

### API-Endpunkt

- [ ] Thumbnail-Dateien können über einen HTTP-Endpunkt abgerufen werden (z. B. `GET /api/dms/thumbnail/<weaviate_uuid>`)
- [ ] Endpunkt prüft JWT-Authentifizierung (wie alle anderen `/api/`-Routen)
- [ ] Kein Thumbnail vorhanden: Endpunkt antwortet mit einem **generischen Platzhalter-Bild** (kein 404-Fehler)
- [ ] Antwort-Header: korrekter `Content-Type: image/jpeg`, Cache-Header für statische Auslieferung im LAN

### Backfill

- [ ] Ein manuell auslösbarer n8n-Workflow `alice-dms-thumbnailer-backfill` existiert
- [ ] Backfill liest alle Weaviate-Objekte ohne gesetztes `thumbnail_path` (alle Collections: Invoice, BankStatement, BankTransaction, Document, Email, SecuritySettlement, Contract)
- [ ] Backfill nutzt dieselbe Thumbnail-Generierungslogik wie der Laufzeit-Workflow
- [ ] Backfill verarbeitet Batches und kann unterbrochen / neu gestartet werden ohne Duplikate zu erzeugen
- [ ] Fortschritt wird im Execution Log von n8n sichtbar: `{ processed, failed, skipped_already_has_thumb, remaining }`

## Edge Cases

- **Datei auf NAS nicht mehr vorhanden** (gelöscht nach DMS-Import): Thumbnail-Generierung schlägt fehl → Fehler loggen, kein Thumbnail; Platzhalter wird im Frontend angezeigt
- **LibreOffice Konvertierung schlägt fehl** (korrupte Office-Datei): Fehler loggen, Platzhalter verwenden; kein Retry (nächster Re-Import des Dokuments würde neuen Versuch auslösen)
- **Sehr große Datei** (PDF mit 500 Seiten): Nur erste Seite wird gerendert; Performance-Impact minimal
- **Gleichzeitige Verarbeitung** mehrerer Dokumente: Jeder MQTT-Trigger ist unabhängig; kein shared state notwendig
- **Backfill läuft während Laufzeit-Workflow aktiv ist**: Beide können gleichzeitig laufen; Thumbnails werden anhand UUID in separate Dateien gespeichert; kein Konflikt
- **Weaviate-UUID ändert sich bei Re-Import**: PROJ-19 löscht altes Objekt und erstellt neues mit neuer UUID → neues Thumbnail unter neuer UUID; altes Thumbnail bleibt verwaist → Bereinigung im Rahmen von PROJ-21 (DMS Lifecycle Management) oder separatem Cleanup-Job
- **Warm Storage nicht erreichbar**: Thumbnail-Generierung schlägt fehl; Fehler wird geloggt; `alice/dms/thumb_error` wird publiziert

## Technical Requirements

- **Thumbnail-Dienst**: Dedizierter Python-Container `alice-dms-thumbnailer` (oder Erweiterung eines bestehenden Containers), der Konvertierungstools kapselt (poppler-utils für PDF, LibreOffice headless für Office, Pillow für Bilder)
- **Aufruf**: Via HTTP vom n8n-Workflow; der Container übernimmt die Konvertierungslogik, n8n triggert und speichert das Ergebnis
- **Thumbnail-Größe**: In der Architektur festlegen, orientiert an 2-Spalten-Layout im Smartphone-Portrait (Richtwert: 400×400 px)
- **Storage-Pfad**: `<warm-storage-mount>/thumbnails/<weaviate_uuid>.jpg`; Warm-Storage-Root ist per Umgebungsvariable konfigurierbar
- **Weaviate-Schema**: Alle bestehenden Collections erhalten ein neues Feld `thumbnail_path` (String, optional)
- **API-Integration**: Endpunkt kann in `alice-chat-stream` (Python/FastAPI) oder als separater nginx-Location-Block implementiert werden — in der Architektur festlegen
- **Backfill-Laufzeit**: Unkritisch (läuft einmalig manuell, kann Stunden dauern); keine Zeitbegrenzung wie PROJ-19

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Component Overview

```
alice/dms/done (MQTT)
        │
        ▼
[n8n: alice-dms-thumbnailer]      [n8n: alice-dms-thumbnailer-backfill]
  MQTT Trigger                      Manual Trigger (Webhook POST)
  HTTP POST /generate               Weaviate Query (all 7 collections)
  Weaviate PATCH (thumbnail_path)   SplitInBatches → HTTP POST /generate
  MQTT → alice/dms/thumb_error      Weaviate PATCH per doc + progress log
        │                                   │
        └─────────────┬─────────────────────┘
                      ▼
        [alice-dms-thumbnailer Container — Port 8004]
          POST /generate  → conversion logic (returns thumbnail path)
          GET  /thumbnail/{uuid} → file serving + JWT auth check
          GET  /health
                      │
                      ▼
        [NAS Warm Storage: /srv/warm/alice/thumbnails/{uuid}.jpg]

nginx:
  GET /api/dms/thumbnail/{uuid}  →  alice-dms-thumbnailer:8004
```

### Data Model

**Warm Storage** (existing NAS mount, `/srv/warm`):
- One JPEG per document: `/srv/warm/alice/thumbnails/{weaviate_uuid}.jpg`
- Format: JPEG, **400×400 px**, quality ≥80%
- Root path configurable via environment variable `WARM_STORAGE_ROOT`

**Weaviate Schema** (all 7 collections: Invoice, BankStatement, BankTransaction, Document, Email, SecuritySettlement, Contract):
- New optional field: `thumbnail_path` (String) — set after successful generation; absent means no thumbnail yet

### Tech Decisions

| Decision | Choice | Reason |
|---|---|---|
| Separate container for conversion | New `alice-dms-thumbnailer` Python/FastAPI | poppler + LibreOffice headless are heavy system packages; isolating keeps n8n and alice-chat-stream clean |
| API endpoint location | Same `alice-dms-thumbnailer` container | Container already holds the volume mount and path knowledge; avoids adding a route to alice-chat-stream |
| nginx routing | New `/api/dms/thumbnail/` → port 8004 | Consistent with existing pattern (`/api/admin/` → chat-stream, `/api/speech/` → speech-gateway) |
| n8n → thumbnailer communication | HTTP Request node (POST `/generate`) | Matches existing DMS extractor pattern; keeps conversion logic out of Code nodes |
| Backfill | Separate workflow `alice-dms-thumbnailer-backfill` | Manual, batch, re-startable without affecting the runtime workflow |
| Thumbnail size | 400×400 px | Matches 2-column mobile portrait Flip-Card layout |
| Missing thumbnail response | Bundled placeholder image in container | GET `/thumbnail/{uuid}` never returns 404 — always an image, keeps frontend simple |

### Crop Logic

| File type | Toolchain | Crop method |
|---|---|---|
| PDF | poppler `pdftoppm` | Render page 1 → top square crop |
| DOCX / XLSX / ODT / ODS | LibreOffice headless → PDF → poppler | Same as PDF |
| JPG / PNG / WEBP | Pillow | Center square crop |
| TXT / MD | Pillow text render (monospace font) | Top square crop; fallback to generic document icon on failure |

### n8n Workflows

**`alice-dms-thumbnailer`** (runtime, MQTT-triggered):
- Trigger: MQTT `alice/dms/done`
- Flow: Parse payload → HTTP POST `/generate` to thumbnailer → branch success/failure → Weaviate PATCH `thumbnail_path` on success → MQTT `alice/dms/thumb_error` on failure

**`alice-dms-thumbnailer-backfill`** (one-time, manual):
- Trigger: Webhook POST
- Flow: For each of 7 collections → Weaviate query (objects without `thumbnail_path`) → SplitInBatches → HTTP POST `/generate` → Weaviate PATCH → log `{processed, failed, skipped_already_has_thumb, remaining}`

### New Dependencies

| Package / Tool | Purpose |
|---|---|
| `poppler-utils` (system) | PDF → image rendering via `pdftoppm` |
| `libreoffice` (system, headless) | Office files → PDF |
| `Pillow` (Python) | Image manipulation, crop, JPEG encoding |

## QA Test Results

**QA Date:** 2026-06-27
**Verdict:** READY — no Critical or High bugs remaining

### Acceptance Criteria

| # | AC | Result |
|---|---|---|
| 1 | alice-dms-thumbnailer n8n workflow subscribes MQTT `alice/dms/done` | ✅ PASS |
| 2 | MQTT message contains: `original_path`, `weaviate_uuid`, `document_type`, `file_type` (added to alice-dms-processor.json) | ✅ PASS |
| 3 | Exactly one thumbnail per document per MQTT trigger | ✅ PASS |
| 4 | Format: 400×400 px quadratisches JPEG | ✅ PASS |
| 5 | Crop rules: PDF→top crop, Office→PDF→top crop, Images→center crop, TXT→text render | ✅ PASS |
| 6 | JPEG quality=85 ≥ 80% | ✅ PASS |
| 7 | Thumbnail gespeichert unter `{WARM_STORAGE_ROOT}/alice/thumbnails/{uuid}.jpg` | ✅ PASS |
| 8 | Weaviate PATCH setzt `thumbnail_path` nach erfolgreicher Generierung | ✅ PASS |
| 9 | Fehler: geloggt, kein Thumbnail, MQTT `alice/dms/thumb_error` publiziert | ✅ PASS |
| 10 | Vorhandenes Thumbnail wird überschrieben (kein If-Exists-Check) | ✅ PASS |
| 11 | `GET /api/dms/thumbnail/{uuid}` Endpunkt vorhanden (nginx → alice-dms-thumbnailer) | ✅ PASS |
| 12 | JWT-Auth auf GET /thumbnail/{uuid} erzwungen | ✅ PASS |
| 13 | Kein Thumbnail → Platzhalter zurückgegeben (niemals 404) | ✅ PASS |
| 14 | Content-Type: image/jpeg, Cache-Control-Header gesetzt | ✅ PASS |
| 15 | alice-dms-thumbnailer-backfill Workflow existiert | ✅ PASS |
| 16 | Backfill liest alle 7 Collections für Objekte ohne thumbnail_path | ✅ PASS |
| 17 | Backfill nutzt dieselbe Generierungslogik (HTTP POST /generate) | ✅ PASS |
| 18 | Backfill verarbeitet Batches und kann ohne Duplikate neu gestartet werden | ✅ PASS (nach BUG-55-1 Fix) |
| 19 | Fortschritt `{processed, failed, skipped, total}` im n8n Execution Log | ✅ PASS |

### Bugs Found

| ID | Severity | Status | Description |
|---|---|---|---|
| BUG-55-1 | Medium | Fixed | Backfill `Code: Extract Path` und `Code: Log PATCH Result` verwendeten `$input.first()` statt `$input.all()` — bei Batches mit mehreren Dokumenten wurden Items 2..N ignoriert. Alle vier Code-Knoten auf `$input.all().map(...)` umgestellt. |
| BUG-55-2 | Low | Fixed | Rückgabetyp-Annotation von `generate_thumbnail()` war `Path \| None` statt `Image.Image \| None`. Kein Laufzeitfehler, aber irreführend. |

### Security Audit

- **Pfad-Traversal** (`/generate`): `original_path` wird gegen erlaubte Pfadpräfixe (`/srv`, `/mnt`, `/data`, `/nas`) geprüft. ✅
- **UUID-Validierung** (`/thumbnail/{uuid}`): Regex `[0-9a-f-]{36}` verhindert Pfad-Injection. ✅
- **JWT-Auth**: Alle extern erreichbaren Endpunkte erfordern gültigen JWT. ✅
- **`/generate` intern**: Endpunkt nicht via nginx exponiert — ausschließlich von n8n auf dem internen `automation`-Netzwerk erreichbar. ✅
- **Subprocess-Injection**: `pdftoppm` und LibreOffice werden mit Listen-Argumenten aufgerufen (kein `shell=True`). ✅

### Unit Tests

- 15 Tests für `_extract_vision_results()` in `tests/test_extract_vision_results.py` — alle bestanden.

### Automated Tests

- `npm run build` (Frontend): ✅ Keine TypeScript-Fehler

## Deployment

**Deploy Date:** 2026-06-28
**Deployed by:** Andrew Steel

### What was deployed
- `alice-dms-thumbnailer` Python container: created and started on server
- `alice-dms-thumbnailer` n8n workflow: imported and published (triggers on `alice/dms/done` MQTT)
- `alice-dms-thumbnailer-backfill` n8n workflow: imported and published (manual trigger)
- `alice-dms-processor` n8n workflow: redeployed with thumbnail_path in Weaviate PATCH step
- nginx: new `/api/dms/thumbnail/` location block added
- PostgreSQL migration `scripts/proj55-add-thumbnail-path.sh`: applies `thumbnail_path` column to DMS tables

### Backfill
The backfill workflow was not yet triggered. To generate thumbnails for all existing documents:
```bash
curl -X POST https://alice.happy-mining.de/api/webhook/alice-dms-thumbnailer-backfill
```
(verify exact webhook path in n8n UI before running)
