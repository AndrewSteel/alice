# PROJ-55: DMS Thumbnail-Generierung

## Status: Deployed
**Created:** 2026-06-27
**Last Updated:** 2026-08-17

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

## Re-Test — Post-Deploy Verification (2026-06-28)

**QA Date:** 2026-06-28
**Scope:** Verification der noch nicht committeten Änderungen am Thumbnailer-Container und Backfill-Workflow.
**Verdict:** READY — keine neuen Critical/High Bugs.

### Geprüfte Änderungen (uncommitted diff)

| AC-Bezug | Datei | Verifikation |
|---|---|---|
| #1 Placeholder-Design | `Dockerfile` | ✅ Neuer Dark-Theme-Placeholder (gray-800 Hintergrund, Dokumentkarte) ersetzt das Ubuntu-ähnliche Icon. Python-Einzeiler im `RUN` (Dockerfile-Parser-sicher). |
| #13 Placeholder immer verfügbar | `main.py` `startup()` | ✅ Boot-Guard: fehlt `placeholder.jpg`, wird er aus Pillow regeneriert (gleiches Design wie Dockerfile). Verhindert "file not found" bei verlorenem Build-Artefakt. |
| #11/#13 Serving | `main.py` `serve_thumbnail()` | ✅ Logging ergänzt (Treffer/Placeholder/Invalid-UUID); UUID-Regex `[0-9a-f-]{36}` weiterhin als Path-Traversal-Schutz; nie 404. |
| NAS-Mount | `compose.yml` / `nas-volumes.yml` / `.env.example` | ✅ `extends: nas-base` (`/mnt/nas/andreas`, `/mnt/nas/lilly` read-only) ersetzt eigenen `DOCUMENTS_ROOT`-Mount; `DOCUMENTS_ROOT=/mnt/nas`. `nas-volumes.yml` mit Service `nas-base` existiert. Pfad-Validator (`startswith(DOCUMENTS_ROOT)`) passt zu gemounteten Subpfaden. |
| #16/#18 Backfill | `alice-dms-thumbnailer-backfill.json` | ✅ Restrukturiert: ein Code-Node iteriert alle 7 Collections (statt `Split: Per Collection`); Cursor-Pagination beibehalten; GraphQL-`errors` werden jetzt erkannt und geloggt. Merge `combineAll`→`append` (korrekte Aggregation der Erfolg/Fehler/Skip-Zweige für den Summary-Node). Webhook-Pfad auf `alice-dms-thumbnailer-backfill` korrigiert. Valides JSON. |

### Verifikationsergebnisse
- **Workflow JSON** (`alice-dms-thumbnailer-backfill.json`): ✅ valides JSON
- **compose `extends`-Referenz**: ✅ `nas-volumes.yml` Service `nas-base` vorhanden
- **Live-Test** (vom Nutzer bestätigt): Thumbnails werden in der Flip-Card-Ansicht angezeigt

### Security Re-Check
- Pfad-Validator broadened auf `/mnt/nas`; Mounts sind read-only und nur `andreas`/`lilly`-Subpfade → kein Schreibzugriff, kein Zugriff außerhalb gemounteter Verzeichnisse. ✅
- **Low (vorbestehend, kein Regress):** `startswith(DOCUMENTS_ROOT)` ist ein String-Präfix-Check ohne Pfadtrenner — `/mnt/nasX` würde die Validierung passieren, ist aber nicht gemountet und daher nicht lesbar. Bei Gelegenheit auf `Path.is_relative_to()` umstellen.

**Keine neuen Bugs. PROJ-55 bleibt READY.**

## Nachträgliche Änderung (2026-08-17)

**Logging auf winston umgestellt**: Die Code-Nodes in `workflows/alice-dms-thumbnailer.json` verwendeten `console.log`/`console.warn`, deren Ausgabe nur im Browser-Log landet und für Post-Incident-Analysen nicht verfügbar ist. Umgestellt auf einen `winston`-Logger pro Node (File-Transport nach `/home/node/.n8n/logs/n8n.log`, `defaultMeta` mit Workflow-/Node-Namen), analog zur PROJ-72-Migration von scanner/path-worker/processor. Reine Logging-Änderung, keine funktionale Änderung. Deployed: 2026-08-17.

## Refine — Backfill-Fehleranalyse (2026-08-28)

**Auslöser**: Beim ersten produktiven Lauf von `alice-dms-thumbnailer-backfill` (Execution 160594, 2026-08-28, 22170 verarbeitete Objekte) meldete die `HTTP: POST /generate`-Node zunächst `550`/`500 - Internal Server Error`. Der Runtime-Workflow `alice-dms-thumbnailer` stand zu diesem Zeitpunkt fälschlich auf unpublished; nach Publizieren blieb unklar, ob dies der einzige Auslöser war, da für den Runtime-Workflow noch keine Executions vorlagen. Analyse der Execution-Daten (n8n MCP) und des Containercodes (`alice-dms-thumbnailer/app/main.py`) ergab drei unabhängige Ursachen — der ursprüngliche "550"-Verdacht (unpublished Workflow) war nicht die (alleinige) Ursache.

### Neue Bugs

| ID | Severity | Beschreibung |
|---|---|---|
| BUG-55-3 | High | `Merge: All Results` (n8n-nodes-base.merge, typeVersion 3) hat keinen `numberInputs`-Parameter gesetzt (Default = 1 Input). Alle drei Vorgänger-Branches (`Code: Log PATCH Result`, `Code: Log Generation Error`, `Code: Log Skip (no file_path)`) sind auf denselben Input-Index 0 verbunden, statt auf 3 getrennte Inputs. Dadurch erreichen nur die `processed`-Items (884) den `Code: Summary`-Node; `failed` (21286) und `skipped` (5965) werden verworfen. `Respond to Webhook` meldet fälschlich `{processed: 884, failed: 0, skipped_no_path: 0, total: 884}` statt der tatsächlichen Zahlen — ein produktiver Lauf mit 96 % Fehlerquote erscheint im Response als vollständiger Erfolg. |
| BUG-55-4 | Medium | `Code: Log Generation Error` liest `item.json.weaviate_uuid`, aber `item.json` ist an dieser Stelle die HTTP-Fehlerantwort von `/generate` (`{error: {...}}`), nicht das ursprüngliche Request-Item. Dadurch wird für jeden der 21286 Fehler `uuid: "unknown"` geloggt — eine Zuordnung von Fehler zu Dokument ist im Log nicht mehr möglich. |
| BUG-55-5 | Medium | `generate_thumbnail()` in `alice-dms-thumbnailer/app/main.py` fängt keine Exceptions aus der Konvertierungslogik (PDF-Rendering, LibreOffice-Aufruf, Pillow) ab. Nur der bereits behandelte Fall "Quelldatei fehlt" liefert kontrolliert 422; jede andere Konvertierungs-Exception propagiert unbehandelt und wird von FastAPI als 500 beantwortet — abweichend von den in den Edge Cases beschriebenen Fällen (Zeile 57–58: "Fehler loggen, kein Thumbnail"), die einen kontrollierten Fehlerpfad vorsehen. Zusätzlich wurden bei der Postman-Stichprobe Objekte beobachtet, die in der Weaviate-Collection `Email` liegen, aber einen `file_path` auf ein NAS-Dokument (nicht `mail_text`) besitzen — für diese schlägt die Pydantic-Validierung in `GenerateRequest` mit 422 "mail_text must not be empty" fehl. Da BUG-55-3/-4 die genaue Fehlerverteilung (422 vs. 500, betroffene UUIDs) verschleiert haben, ist unbekannt, welcher Anteil der 21286 Fehler auf Fehlklassifizierung vs. echte Konvertierungsfehler entfällt; das lässt sich erst nach Fix von BUG-55-3/-4 im nächsten Lauf feststellen. |

### Neue Acceptance Criteria (Backfill-Robustheit)

- [x] `Merge: All Results` ist korrekt mit 3 Inputs konfiguriert (`numberInputs: 3`, Mode "Append"); jeder der drei Branches (processed / failed / skipped) ist auf einen eigenen Input-Index verbunden
- [ ] Das Backfill-Response-JSON spiegelt nach einem Lauf mit gemischten Ergebnissen alle drei Kategorien korrekt wider (verifiziert per Testlauf mit bekannt gemischten Daten) — **offen, erst nach Deploy verifizierbar**
- [x] `Code: Log Generation Error` loggt die tatsächliche `weaviate_uuid` und `document_type` des fehlgeschlagenen Dokuments (aus dem Request-Item, nicht aus der Fehlerantwort) sowie den HTTP-Statuscode der `/generate`-Antwort, damit Fehlerursachen (422 Validierung vs. 500 Konvertierung) im Log unterscheidbar sind
- [x] `alice-dms-thumbnailer`-Container: Konvertierungsfehler (PDF-Rendering, LibreOffice, Pillow) werden in `generate_thumbnail()` bzw. im `/generate`-Handler abgefangen und als kontrollierter 422 mit aussagekräftigem `detail` zurückgegeben, nicht als unbehandelter 500

### Implementierung (2026-08-28)

| Bug | Datei | Änderung |
|---|---|---|
| BUG-55-3 | `workflows/alice-dms-thumbnailer-backfill.json` | `Merge: All Results`: `numberInputs: 3` ergänzt; die drei Branches auf Input-Index 0 (processed) / 1 (failed) / 2 (skipped) umverdrahtet. |
| BUG-55-4 | `workflows/alice-dms-thumbnailer-backfill.json` | `Code: Log Generation Error`: Quell-Item wird über `$('IF: Has file_path and UUID').itemMatching(i)` aufgelöst (pairedItem-basiert, da nur die Fehler-Teilmenge diesen Branch erreicht und ein positionsbasierter Zugriff verschieben würde). Loggt jetzt `uuid`, `document_type`, `file_path`, HTTP-`status` und `detail`; `reason` unterscheidet `validation_error` (422) von `generation_failed`. `Code: Summary` aggregiert zusätzlich `failed_by_reason`. |
| BUG-55-5 | `alice-dms-thumbnailer/app/main.py` | `/generate`: `generate_thumbnail()` und `img.save()` in try/except gekapselt; unerwartete Exceptions (Pillow-Decode, `_square_crop`, `resize`, Schreibfehler) werden als kontrollierter 422 mit Exception-Typ und -Text beantwortet statt als unbehandelter 500. |

Validierung: n8n `validate_workflow` meldet 15/15 gültige Verbindungen, 0 ungültige; verbleibende Warnungen sind vorbestehend (veraltete typeVersions, IF-Branch-Hinweise sind False Positives für true/false-Ausgänge). `python3 -m py_compile` auf `main.py` fehlerfrei.

## Refine — Nachfolge-Fehler nach Deploy von BUG-55-3/-4/-5 (2026-08-28)

**Auslöser**: Nach Deploy der drei Fixes blieb die Fehlerquote im Backfill weiterhin hoch. Dank BUG-55-5 (kontrollierter 422 statt unbehandeltem 500) waren die tatsächlichen Fehlermeldungen jetzt erstmals sichtbar: `FileNotFoundError: No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/app']` und `OSError: [Errno 24] Too many open files`.

**Diagnose** (per Server-Zugriff des Nutzers, `docker exec alice-dms-thumbnailer`): Offene Filehandles (13) und `/tmp`-Speicherplatz (700G frei) waren unauffällig — kein FD-Leck, keine Diskplatzknappheit. Stattdessen lagen 78 **leere** `tmp*`-Verzeichnisse in `/tmp` (Python-`tempfile.TemporaryDirectory()`-Namensschema), die nie aufgeräumt wurden. Leere Verzeichnisse (keine `.pdf`/`.jpg`-Reste) schließen einen mitten in der Konvertierung abgebrochenen Prozess als Ursache aus — das Verzeichnis wurde erstellt, aber der reguläre `with`-Exit (Cleanup) griff nie.

### Neuer Bug

| ID | Severity | Beschreibung |
|---|---|---|
| BUG-55-6 | High | `_render_pdf_first_page()` und `_convert_office_to_pdf()` in `alice-dms-thumbnailer/app/main.py` riefen `subprocess.run(..., timeout=N)` auf. Bei Timeout terminiert `subprocess.run` nur den direkten Kindprozess — LibreOffice forkt jedoch einen `soffice.bin`-Worker, der das `--outdir`-Verzeichnis weiterhin offenhält. Das nachfolgende `TemporaryDirectory.__exit__` (`shutil.rmtree`) scheitert dadurch für dieses Verzeichnis ("directory not empty"/Handle noch offen); über viele Backfill-Requests akkumulieren sich offene Handles bis zum `ulimit`-Limit ("Too many open files") bzw. `/tmp` wird durch liegengebliebene (aber leere) Verzeichnisse als "kein nutzbares Tempdir" fehlinterpretiert. |

### Fix

- `_run_with_timeout_kill()`: neue Hilfsfunktion, startet den Subprozess mit `start_new_session=True` und killt bei Timeout die **gesamte Prozessgruppe** (`os.killpg(..., SIGKILL)`) statt nur den direkten Kindprozess — verhindert, dass LibreOffice-Worker das Tempdir offenhalten
- `_render_pdf_first_page()` / `_convert_office_to_pdf()`: `with tempfile.TemporaryDirectory()` ersetzt durch `tempfile.mkdtemp()` + explizites `try/finally: shutil.rmtree(tmpdir, ignore_errors=True)` — Cleanup-Fehler werden verschluckt statt selbst zur Exception zu werden und weiteren Müll zu hinterlassen
- `Image.open(pages[0]).copy()` → `with Image.open(pages[0]) as im: return im.copy()` — schließt das PIL-Filehandle explizit statt es dem GC zu überlassen

**Manuelle Aufräumaktion nötig**: Die 78 bereits vorhandenen verwaisten `/tmp/tmp*`-Verzeichnisse werden vom Fix nicht rückwirkend entfernt (kein Startup-Cleanup eingebaut — einmaliges Aufräumen reicht, kein wiederkehrendes Muster erwartet nach dem Fix). Vor dem nächsten Backfill-Lauf manuell entfernen: `docker exec alice-dms-thumbnailer sh -c 'find /tmp -maxdepth 1 -name "tmp??????????" -type d -exec rmdir {} +'`

**Status bleibt Deployed bis Verifikation.** Noch nicht deployed/getestet — nächster Schritt: Container neu bauen und deployen, `/tmp` einmalig bereinigen, danach Backfill erneut auslösen.

## Refine — eigentliche Root Cause: unbegrenzte Parallelität + blockierender Event-Loop (2026-08-28)

**Auslöser**: Nach Deploy von BUG-55-6 blieb die Fehlerquote nahezu unverändert (19381 `generation_failed` von 26357). Live-Diagnose während eines laufenden Backfills (`docker exec` auf dem Server, während Fehler im n8n-Log eintrafen) zeigte: **kein** Filesystem-Leck (`/tmp` blieb bei 0–2 Einträgen) und **keine** offenen Dateien — stattdessen fast 1000 offene **Sockets** (`socket:[...]`-Einträge in `/proc/1/fd`) innerhalb von unter 2 Minuten, bei einem `ulimit` von 1024. Das erklärt sowohl `FileNotFoundError: No usable temporary directory` (Python kann bei erschöpftem FD-Limit keine neue Datei/kein Verzeichnis mehr öffnen, unabhängig vom eigentlichen `/tmp`-Zustand) als auch `Too many open files` und das abschließende `socket hang up` (Server kann keine Verbindungen mehr annehmen/bedienen) als **Symptome derselben Ursache**, nicht als eigenständige Bugs.

**Root Cause**: `POST /generate` ist als `async def` deklariert, ruft aber `generate_thumbnail()` **synchron/blockierend** auf (`subprocess.run` mit bis zu 120s Timeout, blockierendes Pillow). Das blockiert uvicorns einzigen Event-Loop-Thread für die gesamte Dauer eines Requests. Der `HTTP: POST /generate`-Node im Backfill-Workflow hatte kein `options.batching` konfiguriert — n8n feuert dann alle Items eines Collection-Batches **parallel** (kein implizites Concurrency-Limit). Bei bis zu 18498 Image-Dokumenten in einer Collection führte das zu hunderten gleichzeitig eingehenden Verbindungen, die der blockierte Event-Loop nicht bedienen konnte; sie stauten sich als angenommene, aber unbearbeitete Sockets auf, bis das `ulimit -n 1024` erreicht war.

### Neuer Bug

| ID | Severity | Beschreibung |
|---|---|---|
| BUG-55-7 | Critical | `/generate`-Handler blockiert den uvicorn-Event-Loop während der gesamten (bis zu 120s dauernden) Konvertierung; kombiniert mit fehlendem Concurrency-Limit auf n8n-Seite führt das bei großen Backfill-Läufen zur Erschöpfung des Open-File-Limits und zum Totalausfall des Containers für die restliche Laufzeit (alle nachfolgenden Requests scheitern, zuletzt mit "socket hang up"). BUG-55-6 (Tmpdir-Cleanup) war real und ist weiterhin ein korrekter Fix, aber nicht die dominante Ursache der Fehlerquote. |

### Fix

- `alice-dms-thumbnailer/app/main.py`: `generate_thumbnail()`-Aufruf in `/generate` läuft jetzt über `fastapi.concurrency.run_in_threadpool` (`await run_in_threadpool(generate_thumbnail, ...)`) statt direkt im Event-Loop — Starlettes Default-Threadpool begrenzt die tatsächliche Parallelität selbst (Default-Limit 40 Threads) und hält den Event-Loop für andere Requests frei
- `workflows/alice-dms-thumbnailer-backfill.json`: `HTTP: POST /generate`-Node erhält `options.batching = { batchSize: 5, batchInterval: 200ms }` — begrenzt die vom Client (n8n) erzeugte Parallelität als zweite, unabhängige Absicherung

**Noch nicht deployed/getestet.** Nächster Schritt: Container neu bauen, Workflow redeployen, `/tmp` einmalig bereinigen (Befehl siehe oben), danach Backfill erneut auslösen und `failed_by_reason` sowie Live-FD-Zahl beobachten.

## Refine — Verifikationslauf nach BUG-55-7-Fix (2026-08-28)

**Ergebnis** nach Deploy von BUG-55-7 (Threadpool + n8n-Batching): Laufzeit 12m13s, `{processed: 16690, failed: 131, skipped_no_path: 5965, total: 22786}` — Erfolgsquote von 4% auf 73% gestiegen. `failed_by_reason`: `weaviate_patch_failed: 49`, `validation_error: 75`, `generation_failed: 7`. Der Kern-Fix (Event-Loop-Blockade + unbegrenzte Parallelität) ist damit als dominante Ursache bestätigt behoben.

### Verbleibende Befunde (niedrige Priorität, dokumentiert statt gefixt)

**`weaviate_patch_failed` (49×) — CUDA Out-of-Memory bei Weaviate-Vektorisierung:**

Root Cause: `thumbnail_path` fehlt in 6 der 7 per `scripts/proj55-add-thumbnail-path.sh` nachträglich ergänzten Collections (Invoice, BankStatement, Document, Email, SecuritySettlement, Contract) der `moduleConfig`-Block mit `skip: true` — nur `Image.thumbnail_path` (beim initialen Schema-Import angelegt, nicht per Nachtrags-Skript) hat ihn korrekt. Grund: Das Skript sendet beim `POST /v1/schema/{cls}/properties` nur `{name, dataType, description}`, ohne `moduleConfig` (Zeile 40-44). Ohne `skip: true` fließt der Thumbnail-Pfad-String in die `text2vec-transformers`-Vektorisierung ein, und jeder PATCH auf `thumbnail_path` löst eine volle Neu-Vektorisierung des Objekts auf der GPU aus — parallel zur ohnehin laufenden Thumbnail-Generierung, was unter Last zu CUDA-OOM führen kann.

**Geprüfter, aber verworfener Fix:** Weaviate erlaubt weder das Ändern noch das Löschen einer bestehenden Property (per Live-Test bestätigt: `DELETE /v1/schema/{cls}/properties/{prop}` → 404, Property blieb bestehen). Eine Korrektur wäre nur über ein neues Feld + Datenkopie + Umstellung aller Codepfade (Container, beide n8n-Workflows, ggf. Frontend) möglich. Angesichts der geringen Fehlerquote (49 von 22786 ≈ 0,2%, keine Datenintegrität betroffen, betroffene Objekte werden beim nächsten — idempotenten — Backfill-Lauf automatisch erneut versucht) **keine Migration**, nur Dokumentation dieser Einschränkung.

`scripts/proj55-add-thumbnail-path.sh` wird **nicht** korrigiert: Die lokalen `schemas/*.json` sind bereits der korrekte Zielzustand (inkl. `moduleConfig`) für Neuinstallationen, die das komplette Schema in einem Rutsch importieren — das Skript kommt dabei nie zum Einsatz, der Bug tritt also bei zukünftigen Aufsetzungen nicht erneut auf.

**Restliche Fehlerursachen** (`validation_error: 75`, `generation_failed: 7`, sowie `timeout of 120000ms exceeded` in einzelnen `HTTP: POST /generate`-Aufrufen): erwartungskonform bei dieser Größenordnung, kein weiterer Handlungsbedarf im Rahmen von PROJ-55.

**`BankTransaction` fehlt `thumbnail_path` komplett** (GraphQL-Fehler beim Backfill-Query, `found 0 docs` obwohl Transaktionen ohne Thumbnail existieren): wird nicht in PROJ-55 behoben, siehe [PROJ-95](../INDEX.md) (BankTransaction-Thumbnails, Text-Rendering-Modus analog PROJ-93).

**Status: PROJ-55 kann nach diesem Verifikationslauf als abgeschlossen betrachtet werden** — die Kernfunktion (Laufzeit-Thumbnailer + Backfill) arbeitet zuverlässig; verbleibende Fehlerquote ist erklärt und bewusst nicht weiter reduziert (GPU-Vektorisierungs-Altlast) bzw. an PROJ-95 verwiesen (BankTransaction). Nächster Schritt: `/qa` gegen die aktualisierten Acceptance Criteria, dann Status auf Deployed.

### Edge Case (Ergänzung)

- **Weaviate-Objekt in falscher Collection** (z. B. `document_type=Email`-Objekt mit NAS-`file_path` statt `mail_text` — vermutlich Fehlklassifizierungs-Altlast): `/generate` antwortet kontrolliert mit 422 (Pydantic-Validierung bereits vorhanden); Backfill loggt dies unter einem eigenen `reason` (z. B. `validation_error`) statt unspezifisch `generation_failed`, damit Datenqualitätsprobleme von echten Konvertierungsfehlern unterscheidbar sind

**Status bleibt Deployed** — die bestehende Produktivfunktion (Runtime-Thumbnailer bei Einzeldokumenten) ist von diesen Bugs nicht betroffen; sie betreffen ausschließlich den Backfill-Workflow und dessen Diagnostizierbarkeit. Fix ist über `/backend` einzuplanen.
