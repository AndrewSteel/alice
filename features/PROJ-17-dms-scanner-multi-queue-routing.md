# PROJ-17: DMS Scanner Multi-Queue-Routing

## Status: Deployed
**Created:** 2026-03-11
**Last Updated:** 2026-03-20

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

## QA Test Results (Re-Test)

**Tested:** 2026-03-20 (re-test; original test: 2026-03-11)
**Artifact:** `workflows/core/alice-dms-scanner.json`
**Tester:** QA Engineer (AI)
**Method:** Static workflow JSON analysis (33 nodes, full connection graph trace)
**Scope:** Original PROJ-17 acceptance criteria + post-deploy bugfixes (ELOOP/Docker volume 2026-03-17, Summary Stats + MQTT Stats 2026-03-20)

### Acceptance Criteria Status (original PROJ-17)

#### AC-1: Workflow publiziert Dateien in typenspezifische Queues statt `alice/dms/new`
- [x] PASS: 4 MQTT Publish nodes present: `MQTT: Publish PDF` (topic `alice/dms/pdf`), `MQTT: Publish OCR` (topic `alice/dms/ocr`), `MQTT: Publish TXT` (topic `alice/dms/txt`), `MQTT: Publish Office` (topic `alice/dms/office`)
- [x] PASS: Switch node `Switch: Route by Type` connects to all 4 MQTT nodes (outputs 0-3)
- [x] PASS: No reference to `alice/dms/new` anywhere in workflow JSON
- [x] PASS: No node named `MQTT: Publish New File` exists

#### AC-2: Routing-Logik
- [x] PASS: `file_type == 'pdf'` AND `needs_ocr == false` -> Output 0 -> `MQTT: Publish PDF` (topic `alice/dms/pdf`) -- combinator "and"
- [x] PASS: `file_type == 'pdf'` AND `needs_ocr == true` -> Output 1 -> `MQTT: Publish OCR` (topic `alice/dms/ocr`) -- combinator "and"
- [x] PASS: `file_type` in `['txt', 'md']` -> Output 2 -> `MQTT: Publish TXT` (topic `alice/dms/txt`) -- combinator "or"
- [x] PASS: `file_type` in `['docx', 'doc', 'odt', 'xlsx', 'xls', 'ods']` -> Output 3 -> `MQTT: Publish Office` (topic `alice/dms/office`) -- combinator "or", all 6 extensions present

#### AC-3: MQTT-Nachrichtenformat identisch mit bisherigem PROJ-16 Format
- [x] PASS: All 4 MQTT nodes use identical message template
- [x] PASS: All 8 original fields present: `file_path`, `detected_at`, `file_size`, `file_hash`, `file_type`, `suggested_type`, `needs_ocr`, `priority`
- [x] PASS: 2 additional fields from PROJ-21 lifecycle: `action` (replace/new), `old_hash` (nullable). Backward-compatible addition.
- [x] PASS: All 4 MQTT nodes use QoS 1

#### AC-4: Queue `alice/dms/new` wird nicht mehr beschrieben
- [x] PASS: No reference to `alice/dms/new` in entire workflow JSON
- [x] PASS: No node named `MQTT: Publish New File` exists

#### AC-5: Alle anderen Scanner-Logiken bleiben unverändert
- [x] PASS: `Schedule: Hourly 07-22` -- cron `0 7-22 * * *` unchanged
- [x] PASS: `PG: Active Folders` -- SQL query unchanged
- [x] PASS: `Code: Scan All Folders` -- recursive scan with SUPPORTED_EXTENSIONS (9 extensions), MAX_DEPTH=10. Updated with `lstatSync` symlink check and ELOOP handling (bugfix 2026-03-17). Core logic unchanged.
- [x] PASS: `Code: Hash + Size` -- SHA-256 hash calculation core logic unchanged. Added Redis INCR for stats counters (bugfix 2026-03-20).
- [x] PASS: `Code: Lifecycle Check` -- lifecycle detection logic unchanged. Added Redis INCR for stats counters and Redis connect() guard (bugfix 2026-03-20).
- [x] PASS: `Wait: 5s Stability` + `Code: Stability Check` -- stability logic unchanged. Added Redis INCR for skipped_files counter (bugfix 2026-03-20).
- [x] PASS: `IF: Is PDF` -> `Code: OCR Check` / `Set: No OCR Needed` -- unchanged
- [x] PASS: `Code: Set Priority` -- >100MB = "low", else "normal" -- unchanged
- [x] PASS: `Code: Mark Queued` -- sAdd to `alice:dms:queued_files` + PROJ-21 replace cleanup unchanged. Added INCR new_files (bugfix 2026-03-20).
- [x] PASS: `Code: Mark Queued` -> `Loop: Files` connection -- unchanged
- [x] PASS: All credential IDs correct (pg-alice: `2YBtxcocRMLQuAdF`, mqtt-alice: `Kqy6cn7hyDDXrBA0`)

#### AC-6: Workflow-Datei `workflows/core/alice-dms-scanner.json` wird aktualisiert
- [x] PASS: File exists with 33 nodes including Switch + 4 MQTT queue nodes + 2 new stats nodes

### Bugfix Verification: ELOOP + Docker Volume (2026-03-17)

#### BF-1: ELOOP symlink handling in Code: Scan All Folders
- [x] PASS: `isSymlink()` helper function uses `lstatSync` to detect server-side CIFS symlinks
- [x] PASS: `readdirSync` catch block has explicit ELOOP logging (`ELOOP skipped (server-side symlink loop)`)
- [x] PASS: Both `Dirent.isSymbolicLink()` check (local) and `lstatSync` check (NFS/CIFS) present
- [x] PASS: `fs.accessSync` errors in folder-level loop are caught with code-specific logging

#### BF-2: Docker volume mount change
- [x] PASS: `nas-volumes.yml` uses direct CIFS mount points (`/mnt/nas/andreas:/mnt/nas/andreas:ro`, `/mnt/nas/lilly:/mnt/nas/lilly:ro`) instead of parent directory
- [x] PASS: n8n `compose.yml` uses `extends: file: ../nas-volumes.yml` for centralized mount management
- [ ] NOTE: `/mnt/nas/stan` is NOT in `nas-volumes.yml`. The bugfix docs mention ENOENT for stan paths. If stan folders are in `dms_watched_folders`, the scanner will log access errors. This may be intentional if stan folders were removed from watched folders.

### Bugfix Verification: Summary Stats + MQTT Stats (2026-03-20)

#### BF-3: Set: Start Time node
- [x] PASS: Node exists as Code node (id: `set-start-time-01-alice-dms-scanner`)
- [x] PASS: Deletes all 4 stats keys (`scanned_files`, `new_files`, `skipped_files`, `errors`) via `client.del()`
- [x] PASS: Sets `alice:dms:scanner:run_start` to `Date.now()` epoch ms
- [x] PASS: Connection chain: `Schedule: Hourly 07-22` -> `Set: Start Time` -> `PG: Active Folders`
- [x] PASS: Returns `$input.all()` -- passes through schedule trigger data to PG node
- [x] FIXED: Redis `client.connect()` now inside try/catch. See BUG-2.

#### BF-4: Redis counter instrumentation in loop nodes
- [x] PASS: `Code: Hash + Size` -- INCR `scanned_files` at top of try block (counts every file entering loop)
- [x] PASS: `Code: Hash + Size` -- on catch: INCR `skipped_files` + RPUSH `errors` with `.catch(() => {})` guard
- [x] PASS: `Code: Lifecycle Check` -- INCR `skipped_files` for `already_processed` and `already_queued`
- [x] PASS: `Code: Lifecycle Check` -- on catch: RPUSH `errors` with `.catch(() => {})` guard
- [x] PASS: `Code: Stability Check` -- INCR `skipped_files` when `size_stable = false`
- [x] PASS: `Code: Mark Queued` -- INCR `new_files` after successful sAdd
- [x] FIXED: `update_path` and `add_path` now counted via `lifecycle_files` counter. See BUG-3.

#### BF-5: Code: Summary Stats reads from Redis
- [x] PASS: Uses `Promise.all()` to read all counters in parallel
- [x] PASS: Reads `run_start` and computes `runtime_seconds` from epoch diff
- [x] PASS: Outputs `started_at` and `completed_at` as ISO strings
- [x] PASS: `scanned_dirs` correctly uses `$('PG: Active Folders').all().length` (not affected by splitInBatches issue since PG node runs before the loop)
- [x] PASS: Error list read via `lRange` only when `lLen > 0`
- [x] PASS: Proper `client.quit()` in finally block

#### BF-6: MQTT: Publish Stats node
- [x] PASS: Topic: `alice/dms/scanner/stats`
- [x] PASS: QoS: 1
- [x] PASS: Message: `={{ JSON.stringify($json) }}` -- publishes full stats JSON
- [x] PASS: Credential: `mqtt-alice` (id: `Kqy6cn7hyDDXrBA0`)
- [x] PASS: Connection: `Code: Summary Stats` -> `MQTT: Publish Stats` (terminal node, no further connections)

### Edge Cases Status

#### EC-1: Unbekannter Dateityp (future-proofing)
- [x] FIXED (BUG-1): Switch fallback output now connects to `Code: Unknown Type Fallback` which logs the error, increments `skipped_files`, and returns to `Loop: Files`.

#### EC-2: MQTT-Queue nicht erreichbar
- [x] PASS: If MQTT publish fails, `Code: Mark Queued` is not reached. File retried next scan.

#### EC-3: pdf-parse schlaegt fehl (needs_ocr Bestimmung)
- [x] PASS: `Code: OCR Check` has `continueOnFail: true`, defaults to `needs_ocr: true`.

#### EC-4: Redis unreachable during stats initialization (new)
- [x] FIXED (BUG-2): `Set: Start Time` now wraps connect() in try/catch. Scan continues without stats on Redis failure.

#### EC-5: Redis unreachable during file hashing (new)
- [x] FIXED (BUG-4): `Code: Hash + Size` now uses `redisOk` flag pattern. Hash computation proceeds regardless of Redis availability.

### Security Audit Results

- [x] No secrets or credentials hardcoded -- all use n8n credential references by ID
- [x] Redis password read via `$env.REDIS_PASSWORD` with try/catch fallback to empty string
- [x] No user input injection risk -- workflow operates on filesystem paths from trusted DB table
- [x] MQTT messages use QoS 1 -- guaranteed delivery
- [x] No new attack surface -- same MQTT broker, same credentials
- [x] File path traversal: Scanner uses `SUPPORTED_EXTENSIONS` whitelist, reads only from `alice.dms_watched_folders`
- [x] No sensitive data in MQTT messages -- only file metadata and stats counters
- [x] Stats Redis keys use dedicated `alice:dms:scanner:stats:` prefix -- no collision with operational keys
- [x] Stats keys are reset at start of each run -- no unbounded growth

### Regression Check (PROJ-16 + PROJ-21)

- [x] Schedule trigger unchanged (hourly 07-22)
- [x] PostgreSQL folder query unchanged
- [x] Recursive scan logic: core unchanged, improved with ELOOP/symlink handling
- [x] Deduplication via Redis unchanged (same key patterns: `alice:dms:processed`, `alice:dms:queued_files`)
- [x] Lifecycle detection unchanged (PROJ-21: path_to_hash, hash_to_paths, replace/update_path/add_path)
- [x] Stability check unchanged (5s wait, size comparison)
- [x] OCR detection unchanged (continueOnFail: true, default needs_ocr: true)
- [x] Priority logic unchanged (>100MB = low)
- [x] All loop paths return to `Loop: Files` (verified: Hash OK false, Route Lifecycle false, Publish Lifecycle, Size Stable false, Mark Queued)
- [x] Sticky note updated to document new Redis stats keys
- [x] Lifecycle MQTT publish to `alice/dms/lifecycle` still connected

### Bugs Found

#### BUG-1: Switch fallback drops unmatched files silently (FIXED)
- **Severity:** Low
- **Description:** Switch node `fallbackOutput: "extra"` has no connected output. Unmatched file types are silently dropped without error logging, and `Redis: Mark Queued` is never reached, causing infinite retry on every scan cycle.
- **Steps to Reproduce:** (Hypothetical) Add `.csv` to SUPPORTED_EXTENSIONS without adding Switch route.
- **Impact:** No current impact -- all 9 supported extensions are covered by 4 Switch routes.
- **Fix:** Added `Code: Unknown Type Fallback` node on Switch output 4 (extra). Logs unknown type, increments `skipped_files`, pushes error to Redis, then returns to `Loop: Files`. File is not retried indefinitely.

#### BUG-2: Set: Start Time Redis failure blocks entire scan run (FIXED)
- **Severity:** Medium
- **Description:** `Set: Start Time` calls `await client.connect()` outside any try/catch. If Redis is temporarily unreachable, the node throws an unhandled error. Because this node is positioned between `Schedule: Hourly 07-22` and `PG: Active Folders`, a Redis outage prevents all file scanning from happening -- even though Redis stats are a non-critical feature.
- **Fix:** Wrapped entire Redis block (connect + del + set) in try/catch. On failure, logs warning and continues scan without stats. Scan is no longer blocked by Redis outage.

#### BUG-3: Stats counter gap for lifecycle events (update_path, add_path) (FIXED)
- **Severity:** Low
- **Description:** Files with `_lifecycle_action` of `update_path` or `add_path` are counted in `scanned_files` (at `Code: Hash + Size`) but are NOT counted in either `new_files` or `skipped_files`. These files pass through `IF: Is Lifecycle Event` false path -> `MQTT: Publish Lifecycle` -> `Loop: Files` without any counter increment.
- **Fix:** Added `Code: Count Lifecycle` node between `MQTT: Publish Lifecycle` and `Loop: Files`. Increments new `lifecycle_files` Redis counter. Added `lifecycle_files` to `Code: Summary Stats` output and `Set: Start Time` reset list. Stats equation: `scanned_files == new_files + skipped_files + lifecycle_files`.

#### BUG-4: Code: Hash + Size Redis connect() failure unhandled (FIXED)
- **Severity:** Low
- **Description:** `Code: Hash + Size` calls `await client.connect()` before the try block. If Redis is unreachable, the node throws. Since this is inside a `splitInBatches` loop, n8n's default error handling may halt the entire loop iteration. However, the hash computation itself does not depend on Redis -- the INCR is purely for stats.
- **Fix:** Wrapped `client.connect()` in try/catch with `redisOk` flag. Hash computation proceeds regardless. Stats INCR calls are guarded by `redisOk` flag and individual `.catch()` handlers. Pattern now matches `Code: Lifecycle Check`.

### Summary
- **Acceptance Criteria (PROJ-17):** 6/6 passed
- **Bugfix Verification (ELOOP):** Passed (code fix + Docker volume fix verified)
- **Bugfix Verification (Stats):** Passed with 3 new bugs found
- **Edge Cases:** 5/5 passed (all fixed in bugfix sprint 2026-03-20)
- **Bugs Found:** 4 total -- ALL FIXED (0 critical, 0 high, 1 medium, 3 low)
- **Security:** Pass -- no issues found
- **Regression (PROJ-16 + PROJ-21):** Pass
- **Production Ready:** YES
- **All bugs fixed 2026-03-20:** BUG-1 (fallback handler), BUG-2 (Redis resilience in Start Time), BUG-3 (lifecycle counter), BUG-4 (Redis resilience in Hash+Size)

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

## Bugfix Summary Stats + MQTT Stats (2026-03-20)

### Probleme

**1. `Code: Summary Stats` lieferte immer falsche Werte**
- `scannedFiles` / `skippedFiles` / `newFiles`: Nodes wie `$('Code: Hash + Size').all()` und `$('Code: Lifecycle Check').all()` wurden innerhalb eines `splitInBatches`-Loops aufgerufen. `.all()` liefert dort immer nur die Daten der letzten Batch-Iteration (1 Item), nicht alle Iterationen.
- `runtimeSeconds`: `$execution.startedAt` existiert in n8n nicht. Es gibt keine globale Variable für den Execution-Start.

**2. Ergebnis wurde nicht weiterverwendet**
- Der Node gab ein JSON-Objekt zurück, das nirgends angebunden war.
- `console.log` schrieb ins Browser-Log (n8n UI Node-Output), nicht in Container-Logs.

### Lösung: Redis-Counter Pattern

Analog zu den Lifecycle-Checks wird ein Redis-Counter-Ansatz verwendet, der über Loop-Iterationen hinweg akkumuliert.

**Neuer Node `Set: Start Time`** (Code-Node, vor `PG: Active Folders`):
- Resettet alle Run-Stats-Counter in Redis (`DEL`)
- Speichert Startzeit: `SET alice:dms:scanner:run_start <epoch_ms>`

**Redis-Keys (werden bei jedem Run resettet):**
| Key | Typ | Beschreibung |
|---|---|---|
| `alice:dms:scanner:run_start` | String | Epoch ms des Run-Starts |
| `alice:dms:scanner:stats:scanned_files` | Counter | Alle Dateien, die in den Loop eintreten |
| `alice:dms:scanner:stats:new_files` | Counter | Erfolgreich in Queue geschriebene Dateien |
| `alice:dms:scanner:stats:skipped_files` | Counter | Übersprungene Dateien (alle Ursachen) |
| `alice:dms:scanner:stats:lifecycle_files` | Counter | Lifecycle-Events (update_path, add_path) |
| `alice:dms:scanner:stats:errors` | List | Fehlermeldungen als Strings |

**Geänderte Nodes (wo INCR/RPUSH aufgerufen wird):**
| Node | Aktion |
|---|---|
| `Code: Hash + Size` | INCR `scanned_files` (immer); bei Hash-Fehler: INCR `skipped_files` + RPUSH `errors` |
| `Code: Lifecycle Check` | bei `already_processed`/`already_queued`: INCR `skipped_files`; bei Redis-Fehler: RPUSH `errors` |
| `Code: Stability Check` | wenn `size_stable = false`: INCR `skipped_files` |
| `Code: Mark Queued` | INCR `new_files` nach erfolgreichem Queue |

**`Code: Summary Stats`** liest alle Counter via `Promise.all()` aus Redis und baut das Stats-JSON inkl. `started_at` und `completed_at`. Kein `console.log` mehr.

**Neuer Node `MQTT: Publish Stats`** (nach `Code: Summary Stats`):
- Topic: `alice/dms/scanner/stats`
- QoS 1
- Publiziert das komplette Stats-JSON — abonnierbar durch externe Workflows oder Monitoring

### Stats-Nachrichtenformat

```json
{
  "scanned_dirs": 3,
  "scanned_files": 142,
  "new_files": 5,
  "skipped_files": 135,
  "lifecycle_files": 2,
  "errors": [],
  "runtime_seconds": 48,
  "started_at": "2026-03-20T10:00:00.123Z",
  "completed_at": "2026-03-20T10:00:48.456Z"
}
```

### Connection-Änderungen

- `Schedule: Hourly 07-22` → **`Set: Start Time`** → `PG: Active Folders` (Set: Start Time eingefügt)
- `Code: Summary Stats` → **`MQTT: Publish Stats`** (neu angebunden)
