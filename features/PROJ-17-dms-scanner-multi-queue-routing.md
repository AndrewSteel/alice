# PROJ-17: DMS Scanner Multi-Queue-Routing

## Status: Deployed
**Created:** 2026-03-11
**Last Updated:** 2026-03-11

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — Workflow `alice-dms-scanner` muss deployed sein
- Requires: PROJ-18 (DMS Extractor Container) — Consumer der neuen Queues müssen vorhanden sein, bevor der Scanner umgestellt wird

## Overview

Erweiterung des bereits deployten `alice-dms-scanner` Workflows (PROJ-16). Statt alle erkannten Dateien in die einzige Queue `alice/dms/new` zu schreiben, wird jede Datei abhängig von ihrem Typ in eine typenspezifische MQTT-Queue geroutet:

| Dateityp | Ziel-Queue |
|---|---|
| `.pdf` mit Textebene (`needs_ocr: false`) | `alice/dms/pdf` |
| `.pdf` ohne Textebene (`needs_ocr: true`) | `alice/dms/ocr` |
| `.txt`, `.md` | `alice/dms/txt` |
| `.docx`, `.doc`, `.odt` | `alice/dms/office` |
| `.xlsx`, `.xls`, `.ods` | `alice/dms/office` |

Diese Aufteilung ermöglicht spezialisierte Docker-Container (PROJ-18), die jeweils nur ihre eigene Queue abarbeiten, ohne dass n8n Zugriff auf NAS-Dateien außerhalb seines Containers benötigt. Die Container können tagsüber parallel zum Scanner arbeiten und die GPU nicht belasten.

Die bisherige Queue `alice/dms/new` entfällt. Redis-Deduplication, Stability-Check und alle anderen Scanner-Logiken aus PROJ-16 bleiben unverändert.

## User Stories

- Als System möchte ich erkannte Dateien in typenspezifische MQTT-Queues routen, damit spezialisierte Container die Extraktion übernehmen können, ohne dass n8n direkten Dateizugriff außerhalb seines Containers benötigt.
- Als Admin möchte ich, dass die bisherige Scan-Logik (Deduplication, Stability-Check, OCR-Detection) unverändert bleibt, damit keine Regression in PROJ-16 entsteht.
- Als System möchte ich, dass das MQTT-Nachrichtenformat in allen Queues identisch bleibt, damit die Extractor-Container ein einheitliches Interface haben.

## Acceptance Criteria

- [ ] Workflow `alice-dms-scanner` publiziert Dateien in typenspezifische Queues statt `alice/dms/new`
- [ ] Routing-Logik:
  - `file_type == 'pdf'` UND `needs_ocr == false` → `alice/dms/pdf`
  - `file_type == 'pdf'` UND `needs_ocr == true` → `alice/dms/ocr`
  - `file_type` in `['txt', 'md']` → `alice/dms/txt`
  - `file_type` in `['docx', 'doc', 'odt', 'xlsx', 'xls', 'ods']` → `alice/dms/office`
- [ ] MQTT-Nachrichtenformat (je Queue) ist identisch mit bisherigem PROJ-16 Format
- [ ] Queue `alice/dms/new` wird nicht mehr beschrieben
- [ ] Alle anderen Scanner-Logiken (Redis-Dedup, Stability-Check, Ordner-Scan, Stats) bleiben unverändert
- [ ] Workflow-Datei `workflows/core/alice-dms-scanner.json` wird aktualisiert

## MQTT Message Format (alle Queues identisch)

```json
{
  "file_path": "/mnt/nas/projekte/kunde-x/2025/rechnung-stadtwerke.pdf",
  "detected_at": "2026-03-09T10:00:00Z",
  "file_size": 125000,
  "file_hash": "sha256:abc123...",
  "file_type": "pdf",
  "suggested_type": "Rechnung",
  "needs_ocr": false,
  "priority": "normal"
}
```

## Edge Cases

- **Unbekannter Dateityp landet durch Erweiterungsfilter (future-proofing)**: Neue Erweiterungen, die später zum Scanner hinzugefügt werden, müssen explizit einer der Queues zugeordnet werden — sonst Fehler loggen und überspringen.
- **MQTT-Queue nicht erreichbar**: Gleiches Verhalten wie PROJ-16 — Fehler loggen, Hash nicht in Redis `queued_files` eintragen (nächste Run versucht es erneut).
- **pdf-parse schlägt fehl (needs_ocr Bestimmung)**: Unverändert zu PROJ-16 — `needs_ocr: true` als Safe Default → Datei geht in `alice/dms/ocr`.

## Technical Requirements

- **Geänderter Node**: Der MQTT-Publish-Node aus PROJ-16 wird durch einen Switch-Node + 4 MQTT-Publish-Nodes ersetzt (einen pro Queue)
- **Switch-Logik**: Basiert auf `file_type` und `needs_ocr`
- **Keine neuen n8n Credentials** notwendig — gleicher MQTT-Broker
- **Workflow-Datei**: `workflows/core/alice-dms-scanner.json` (Update bestehender Datei)
- **Änderungsumfang**: Minimal — nur die letzten Nodes des Workflows (nach Priority-Setzung) werden angepasst

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Was wird gebaut

Eine minimale Erweiterung des bestehenden `alice-dms-scanner` Workflows. Genau **ein Node** wird ersetzt, **vier Nodes** werden neu hinzugefügt. Alle anderen 20+ Nodes des Workflows bleiben vollständig unverändert.

### Wo im Workflow wird geändert

Der gesamte Workflow bleibt bis nach `Code: Set Priority` identisch. Erst dann greift die neue Routing-Logik:

```
[Unverändert — alles bis hierhin bleibt gleich]
    ...
    Code: Scan All Folders
    Loop: Files
    Code: Hash + Size
    IF: Hash OK
    Redis: Check Processed
    IF: Not Processed
    Redis: Check Queued
    IF: Not Queued
    Wait: 5s Stability
    Code: Stability Check
    IF: Size Stable
    IF: Is PDF
    Code: OCR Check / Set: No OCR Needed
    Code: Set Priority
    │
    ▼ [GEÄNDERT AB HIER]
    Switch: Route by Type  ← ERSETZT "MQTT: Publish New File"
    │
    ├── Output 0 (PDF mit Textebene)  → MQTT: Publish → alice/dms/pdf   [NEU]
    ├── Output 1 (PDF gescannt/OCR)   → MQTT: Publish → alice/dms/ocr   [NEU]
    ├── Output 2 (TXT / MD)           → MQTT: Publish → alice/dms/txt   [NEU]
    └── Output 3 (Office-Formate)     → MQTT: Publish → alice/dms/office [NEU]
                                              ↓ (alle 4 → gleicher Ziel-Node)
    Redis: Mark Queued  ← UNVERÄNDERT
    │
    ▼
    Loop: Files  ← UNVERÄNDERT
```

### Switch-Routing-Logik (PM-lesbar)

Der Switch-Node prüft zwei Felder jeder Datei — Typ und OCR-Flag — und leitet dann in den richtigen Kanal:

| Bedingung | Ziel-Queue |
|---|---|
| Dateityp = `pdf` UND `needs_ocr = false` | `alice/dms/pdf` |
| Dateityp = `pdf` UND `needs_ocr = true` | `alice/dms/ocr` |
| Dateityp = `txt` oder `md` | `alice/dms/txt` |
| Dateityp = `docx`, `doc`, `odt`, `xlsx`, `xls`, `ods` | `alice/dms/office` |

Der n8n Switch-Node unterstützt mehrere Ausgänge mit jeweils eigenen Bedingungen — genau das richtige Werkzeug für diesen Fall.

### MQTT-Nachrichtenformat

Die 4 neuen MQTT-Nodes verwenden exakt dasselbe JSON-Format wie der bisherige `MQTT: Publish New File` Node — kopiert 1:1. Nur der Topic-Name (`alice/dms/pdf` statt `alice/dms/new` etc.) ändert sich. Das schützt gegen Regressionen.

### Zusammenführung nach dem Switch

Alle 4 MQTT-Nodes verbinden sich jeweils mit dem bestehenden `Redis: Mark Queued` Node. In n8n ist es möglich, mehrere Quell-Nodes mit demselben Ziel-Node zu verbinden — der Ziel-Node verarbeitet jeden eingehenden Datensatz einzeln. Die nachgelagerte Loop-Logik arbeitet dadurch ohne Änderung korrekt weiter.

### Änderungsumfang

| Node | Aktion |
|---|---|
| `MQTT: Publish New File` | **Entfernen** |
| `Switch: Route by Type` | **Neu** |
| `MQTT: Publish → alice/dms/pdf` | **Neu** |
| `MQTT: Publish → alice/dms/ocr` | **Neu** |
| `MQTT: Publish → alice/dms/txt` | **Neu** |
| `MQTT: Publish → alice/dms/office` | **Neu** |
| Alle anderen Nodes (20+) | **Unverändert** |

**Keine neuen Credentials** — alle 4 neuen MQTT-Nodes verwenden dieselbe bestehende Credential `mqtt-alice` (`Kqy6cn7hyDDXrBA0`).

### Infrastruktur-Anforderungen

Keine neuen Infrastruktur-Komponenten. Die Queues `alice/dms/pdf`, `alice/dms/ocr`, `alice/dms/txt`, `alice/dms/office` entstehen automatisch beim ersten Publish im MQTT-Broker (Mosquitto erstellt Topics on-demand). Es müssen keine Topics manuell angelegt werden.

### Abhängigkeit zu PROJ-18 (Deployment-Reihenfolge)

Der Scanner kann technisch sofort auf die neuen Queues umgestellt werden — jedoch **sollten die Extractor-Container (PROJ-18) vorher deployed sein**, damit Nachrichten in den Queues nicht unbearbeitet liegen. Empfohlene Reihenfolge: PROJ-18 Container deployen → dann PROJ-17 Workflow deployen.

## QA Test Results

**Tested:** 2026-03-11
**Artifact:** `workflows/core/alice-dms-scanner.json`
**Tester:** QA Engineer (AI)
**Method:** Static workflow JSON analysis (n8n workflow already deployed)

### Acceptance Criteria Status

#### AC-1: Workflow publiziert Dateien in typenspezifische Queues statt `alice/dms/new`
- [x] 4 MQTT Publish nodes present: `MQTT: Publish PDF` (topic `alice/dms/pdf`), `MQTT: Publish OCR` (topic `alice/dms/ocr`), `MQTT: Publish TXT` (topic `alice/dms/txt`), `MQTT: Publish Office` (topic `alice/dms/office`)
- [x] Switch node `Switch: Route by Type` connects to all 4 MQTT nodes
- [x] No reference to `alice/dms/new` anywhere in workflow JSON
- [x] No node named `MQTT: Publish New File` exists

#### AC-2: Routing-Logik
- [x] `file_type == 'pdf'` AND `needs_ocr == false` -> Output 0 -> `MQTT: Publish PDF` (topic `alice/dms/pdf`) -- Switch rule uses string equals "pdf" AND boolean equals false, combinator "and"
- [x] `file_type == 'pdf'` AND `needs_ocr == true` -> Output 1 -> `MQTT: Publish OCR` (topic `alice/dms/ocr`) -- Switch rule uses string equals "pdf" AND boolean equals true, combinator "and"
- [x] `file_type` in `['txt', 'md']` -> Output 2 -> `MQTT: Publish TXT` (topic `alice/dms/txt`) -- Switch rule uses string equals "txt" OR string equals "md", combinator "or"
- [x] `file_type` in `['docx', 'doc', 'odt', 'xlsx', 'xls', 'ods']` -> Output 3 -> `MQTT: Publish Office` (topic `alice/dms/office`) -- Switch rule checks all 6 extensions with combinator "or"

#### AC-3: MQTT-Nachrichtenformat identisch mit bisherigem PROJ-16 Format
- [x] All 4 MQTT nodes use identical message template
- [x] All 8 required fields present: `file_path`, `detected_at`, `file_size`, `file_hash`, `file_type`, `suggested_type`, `needs_ocr`, `priority`
- [x] Format matches spec: `JSON.stringify({ file_path, detected_at, file_size, file_hash, file_type, suggested_type, needs_ocr, priority })`
- [x] All 4 MQTT nodes use QoS 1 (same as PROJ-16)

#### AC-4: Queue `alice/dms/new` wird nicht mehr beschrieben
- [x] No reference to `alice/dms/new` in entire workflow JSON (verified via grep)
- [x] No node named `MQTT: Publish New File` exists

#### AC-5: Alle anderen Scanner-Logiken bleiben unverändert
- [x] `Schedule: Hourly 07-22` -- cron `0 7-22 * * *` unchanged
- [x] `PG: Active Folders` -- SQL query unchanged (`SELECT id, path, suggested_type FROM alice.dms_watched_folders WHERE enabled = true`)
- [x] `Code: Scan All Folders` -- recursive scan with SUPPORTED_EXTENSIONS unchanged (includes all 9 extensions)
- [x] `Code: Hash + Size` -- SHA-256 hash calculation unchanged
- [x] Redis dedup chain: `Redis: Check Processed` -> `IF: Not Processed` -> `Redis: Check Queued` -> `IF: Not Queued` -- unchanged
- [x] `Wait: 5s Stability` + `Code: Stability Check` -- unchanged
- [x] `IF: Is PDF` -> `Code: OCR Check` / `Set: No OCR Needed` -- unchanged
- [x] `Code: Set Priority` -- >100MB = "low", else "normal" -- unchanged
- [x] `Redis: Mark Queued` -- set key `alice:dms:queued:{hash}` = "1" -- unchanged
- [x] `Redis: Mark Queued` -> `Loop: Files` connection -- unchanged
- [x] All credential IDs match expected values (pg-alice: `2YBtxcocRMLQuAdF`, redis-alice: `DtO8rm7fWa7IYMen`, mqtt-alice: `Kqy6cn7hyDDXrBA0`)

#### AC-6: Workflow-Datei `workflows/core/alice-dms-scanner.json` wird aktualisiert
- [x] File exists and contains the updated workflow with Switch + 4 MQTT nodes

### Edge Cases Status

#### EC-1: Unbekannter Dateityp (future-proofing)
- [ ] BUG: Switch node has `fallbackOutput: "extra"` configured, which means unmatched file types silently go to an extra output. However, the extra output (index 4) has NO connection -- items are silently dropped without logging an error, and critically, without going to `Redis: Mark Queued`. This means unmatched files will be retried every scan cycle indefinitely. See BUG-1.

#### EC-2: MQTT-Queue nicht erreichbar
- [x] Handled correctly -- if an MQTT publish node fails, the subsequent `Redis: Mark Queued` node is not reached, so the file will be retried on the next scan run. This is the same behavior as PROJ-16.

#### EC-3: pdf-parse schlaegt fehl (needs_ocr Bestimmung)
- [x] `Code: OCR Check` has `continueOnFail: true` set and defaults to `needs_ocr: true` on error. File would route to `alice/dms/ocr` as expected.

### Security Audit Results

- [x] No secrets or credentials hardcoded -- all use n8n credential references by ID
- [x] No user input injection risk -- workflow operates on filesystem paths from trusted DB table `alice.dms_watched_folders`
- [x] MQTT messages use QoS 1 -- guaranteed delivery, no message loss
- [x] No new attack surface introduced -- same MQTT broker, same credential
- [x] File path traversal: Scanner uses `SUPPORTED_EXTENSIONS` whitelist and reads only from folders stored in `alice.dms_watched_folders` (admin-controlled via PROJ-15 with auth)
- [x] No sensitive data exposure in MQTT messages -- only file metadata, no file content

### Regression Check (PROJ-16)

- [x] Schedule trigger unchanged (hourly 07-22)
- [x] PostgreSQL folder query unchanged
- [x] Recursive scan logic unchanged (same extensions, same MAX_DEPTH=10)
- [x] Deduplication via Redis unchanged (same key patterns)
- [x] Stability check unchanged (5s wait, size comparison)
- [x] OCR detection unchanged (Font marker in first 64KB)
- [x] Priority logic unchanged (>100MB = low)
- [x] Loop flow unchanged (all paths return to `Loop: Files`)
- [x] Sticky note updated to reflect new queue structure

### Bugs Found

#### BUG-1: Switch fallback drops unmatched files silently (no error, no Redis mark)
- **Severity:** Low
- **Description:** The Switch node has `fallbackOutput: "extra"` configured but the extra output has no connection. If a future extension is added to `SUPPORTED_EXTENSIONS` in the scan code but not to the Switch routing rules, files of that type would silently be dropped. Worse, since `Redis: Mark Queued` is never reached, these files will be retried on every single scan cycle indefinitely, wasting hash computation and Redis lookups each hour.
- **Steps to Reproduce:**
  1. (Hypothetical) Add a new extension like `.csv` to `SUPPORTED_EXTENSIONS` in `Code: Scan All Folders`
  2. Do NOT add a corresponding route in `Switch: Route by Type`
  3. Place a `.csv` file in a watched folder
  4. Expected: Error is logged and file is skipped (as per spec edge case EC-1)
  5. Actual: File silently dropped, no error logged, retried every scan cycle
- **Impact:** Currently no impact because all 9 supported extensions are covered by the 4 Switch routes. This is purely a future-proofing issue.
- **Priority:** Nice to have -- connect fallback output to `Loop: Files` (skip) or add a logging node. Current extensions are fully covered.

### Summary
- **Acceptance Criteria:** 6/6 passed
- **Edge Cases:** 2/3 passed, 1 low-severity future-proofing gap (BUG-1)
- **Bugs Found:** 1 total (0 critical, 0 high, 0 medium, 1 low)
- **Security:** Pass -- no issues found
- **Regression (PROJ-16):** Pass -- all scanner logic unchanged
- **Production Ready:** YES
- **Recommendation:** Deploy. BUG-1 is a future-proofing issue with no current impact -- fix it when adding new file extensions to the scanner.

## Deployment

**Deployed:** 2026-03-11
**Workflow:** `alice-dms-scanner` (imported via n8n UI)
**Status:** Active — routing to 4 queues: `alice/dms/pdf`, `alice/dms/ocr`, `alice/dms/txt`, `alice/dms/office`

## Post-Deploy Bugfix (2026-03-17): ELOOP + Docker Volume

### Problem
`Code: Scan All Folders` warf `ELOOP: too many symbolic links encountered` für Pfade unter `/mnt/nas/andreas` und `/mnt/nas/lilly`, und `ENOENT` für alle Pfade unter `/mnt/nas/stan`.

### Root Causes (zwei separate Ursachen)

**1. ELOOP (`/mnt/nas/andreas`, `/mnt/nas/lilly`):**
Die alten fstab-Einträge mounten NAS-Pfade mit zirkulären Unterpfaden:
```
//192.168.178.103/homes/stan/Dokumente/mini/home/stan → /mnt/nas/andreas
```
Der Pfad `Dokumente/mini/home/stan` enthält einen serverseitigen CIFS-Symlink (`mini`), der zurück ins Home-Verzeichnis zeigt. Der Linux-Kernel meldet ELOOP sobald `access()` auf diesen Pfad aufgerufen wird. `find -type l` findet den Symlink nicht, weil der CIFS-Client ihn als reguläres Verzeichnis anzeigt.

**2. ENOENT (`/mnt/nas/stan/Dokumente` etc.):**
Docker mount propagation: `compose.yml` mountete `/mnt/nas:/mnt/nas:ro`. Mit Standard-Propagation `rprivate` sieht der Container die CIFS-Submounts (`/mnt/nas/stan`, `/mnt/nas/andreas`, `/mnt/nas/lilly`) als leere Verzeichnisse — die CIFS-Dateisysteme werden nicht in den Container propagiert.

### Fix

**Code (`Code: Scan All Folders`):**
- `lstatSync`-basierte Symlink-Prüfung ergänzt (erkennt NFS/CIFS-seitige Symlinks zuverlässiger als `Dirent.isSymbolicLink()`)
- ELOOP-spezifisches Logging in `readdirSync`-catch hinzugefügt
- Verbose Error-Logging für alle Fehlerarten

**Infrastruktur (`docker/compose/automations/n8n/compose.yml`):**
```yaml
# Vorher (funktioniert nicht — Submounts nicht propagiert):
- /mnt/nas:/mnt/nas:ro

# Nachher (direktes Bind-Mount des CIFS-Dateisystems):
- /mnt/nas/stan:/mnt/nas/stan:ro
```
Durch direktes Mounten des CIFS-Filesystems (statt des Parent-Verzeichnisses) sieht der Container den Inhalt vollständig.

### Erkenntnisse für künftige NAS-Mounts
- Immer das CIFS-Filesystem selbst mounten, nicht ein Parent-Verzeichnis das CIFS-Submounts enthält
- `console.log` in n8n Code Nodes erscheint im **n8n UI Node-Output** (Browser), nicht in Docker Container-Logs
- Serverseitige CIFS-Symlinks sind mit `find -type l` nicht sichtbar, erzeugen aber ELOOP auf dem Client
