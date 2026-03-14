# PROJ-21: DMS Lifecycle Management (Duplikate, Verschiebungen, Dateiänderungen)

## Status: Deployed
**Created:** 2026-03-12
**Last Updated:** 2026-03-14

## Dependencies
- Requires: PROJ-17 (DMS Scanner Multi-Queue) — Workflow `alice-dms-scanner` muss deployed sein
- Requires: PROJ-19 (DMS Processor) — Redis-Mappings `alice:dms:path_to_hash` und `alice:dms:hash_to_paths:<hash>` müssen vom Processor befüllt werden
- Weaviate Collections müssen existieren (PROJ-19)

## Overview

Erweiterung des `alice-dms-scanner` Workflows und des `alice-dms-processor` Workflows um die Erkennung und Behandlung von drei Datei-Lifecycle-Ereignissen, die über den Normalfall (neue Datei) hinausgehen:

| Fall | Beschreibung | Erkennung | Behandlung |
|---|---|---|---|
| **Fall 1 – Duplikat** | Gleicher Inhalt (Hash), anderer Pfad, Originalpfad noch vorhanden | Scanner | Weaviate-Eintrag um neuen Pfad erweitern (kein LLM-Aufruf) |
| **Fall 2 – Verschiebung** | Gleicher Inhalt (Hash), anderer Pfad, Originalpfad verschwunden | Scanner | Weaviate-Eintrag: `original_path` auf neuen Pfad aktualisieren (kein LLM-Aufruf) |
| **Fall 3 – Dateiänderung** | Gleicher Pfad, anderer Hash | Scanner erkennt, Processor behandelt | Weaviate: ALTER Eintrag löschen, NEUEN Eintrag vollständig verarbeiten (LLM-Aufruf) |

**Fall 4 (Dateilöschung)** ist explizit nicht Teil dieses Projekts. Da gelöschte Dateien keinen Scan-Event erzeugen, kann dieser Fall nicht im Scanner erkannt werden. Er erfordert einen eigenständigen Reconciliation-Sprint.

Die Grundlage für alle drei Fälle sind die Redis-Mappings, die PROJ-19 nach jedem erfolgreichen Weaviate-Insert befüllt:
- `alice:dms:path_to_hash` (Redis Hash) — Pfad → Hash
- `alice:dms:hash_to_paths:<hash>` (Redis Set) — Hash → alle bekannten Pfade

## User Stories

- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei an einen anderen Ort kopiert wurde (Duplikat), damit der neue Pfad in Weaviate als zusätzlicher Zugriffspfad hinterlegt wird.
- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei verschoben wurde, damit der veraltete Pfad in Weaviate aktualisiert wird und Suchergebnisse nicht auf nicht-existente Pfade zeigen.
- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei inhaltlich geändert wurde (gleicher Pfad, neuer Inhalt), damit der veraltete Weaviate-Eintrag ersetzt und die neuen Inhalte vollständig klassifiziert und indiziert werden.
- Als Admin möchte ich, dass Duplikat- und Verschiebungs-Erkennungen ohne LLM-Aufruf ablaufen, damit die GPU nicht unnötig belastet wird.

## Acceptance Criteria

### Scanner-Erweiterung (alice-dms-scanner)

- [ ] Für jede gescannte Datei: nach Hash-Berechnung Lookup in `alice:dms:path_to_hash` (HGET mit `file_path`)
  - [ ] Ergebnis: bekannter Hash für diesen Pfad (→ Fall 3 prüfen) oder kein Eintrag (→ Normalpfad)
- [ ] **Fall 3 (Dateiänderung)**: `path_to_hash[file_path]` vorhanden UND gespeicherter Hash ≠ aktueller Hash
  - [ ] Datei wird mit `action: "replace"` und `old_hash` in die typenspezifische MQTT-Queue gestellt
  - [ ] Alter Hash wird aus `alice:dms:processed` entfernt (`SREM`) → erzwingt Neuverarbeitung
  - [ ] Alter Hash wird in `alice:dms:queued_files` nicht nochmals eingetragen (new hash wird gequeuet)
- [ ] Für Dateien mit bereits bekanntem Hash (bisher: skip): `alice:dms:hash_to_paths:<hash>` prüfen
  - [ ] **Fall 1 (Duplikat)**: Hash bekannt, bekannte Pfade in `hash_to_paths` existieren noch alle auf NAS → `action: "add_path"` direkt an Processor-Queue (ohne Textextraktion)
  - [ ] **Fall 2 (Verschiebung)**: Hash bekannt, alle bekannten Pfade in `hash_to_paths` existieren NICHT mehr auf NAS → `action: "update_path"` direkt an Processor-Queue (ohne Textextraktion)
- [ ] Für Fälle 1 und 2: Nachrichten gehen direkt in eine neue Queue `alice/dms/lifecycle` (kein Extractor-Umweg, da kein Plaintext benötigt)

### Weaviate-Schema-Erweiterung

- [ ] Alle 6 Collections erhalten ein zusätzliches Feld `additional_paths` (Array of String) für Duplikat-Pfade
- [ ] `original_path` bleibt als primäres Feld erhalten

## Edge Cases

- **Weder Fall 1 noch Fall 2 eindeutig** (einige bekannte Pfade existieren noch, andere nicht): Behandlung als Fall 1 (konservativ, kein Datenverlust). Nicht mehr existente Pfade werden aus `hash_to_paths` entfernt, neue Pfade hinzugefügt.
- **`hash_to_paths` leer obwohl Hash in `processed`** (Inkonsistenz, z.B. aus Altdaten vor PROJ-21): Behandlung wie neue Datei — Skip des Lifecycle-Checks, normaler Prozessfluss.
- **Fall 3: Dateiänderung + gleichzeitiger LLM-Timeout**: Normales Fehlerverhalten des Processors — alter Hash wurde bereits aus `processed` entfernt; beim nächsten Nacht-Lauf wird die Datei erneut verarbeitet.
- **Pfad-Check auf NAS schlägt fehl** (NAS nicht erreichbar): Lifecycle-Checks für Fall 1/2 werden übersprungen; Scanner loggt Warnung. Nächster Scan-Run versucht es erneut.
- **Mehrere Verschiebungen in Folge**: Jede Verschiebung wird als eigenes Lifecycle-Event erkannt; `hash_to_paths` und `path_to_hash` werden bei jeder Operation konsistent aktualisiert.

## Technical Requirements

- **Geänderte Workflows**: `alice-dms-scanner` (Lifecycle-Erkennung + Routing) + `alice-dms-processor` (Fall-3-Handling bereits via PROJ-19 Dedup-before-insert abgedeckt)
- **Neue MQTT-Queue**: `alice/dms/lifecycle` — für Fälle 1 und 2; wird von `alice-dms-lifecycle` (PROJ-22) konsumiert
- **NAS-Pfad-Check im Scanner**: Datei-Existenz-Prüfung — Scanner muss NAS-Zugriff haben (bereits vorhanden via NAS-Mount in n8n)
- **Keine neuen n8n Credentials** — gleiche wie PROJ-19
- **Workflow-Datei**: `workflows/core/alice-dms-scanner.json`
- **Verarbeitung der lifecycle Queue**: eigenständiger Workflow `alice-dms-lifecycle` (PROJ-22)

## Lifecycle-Nachrichtenformat (alice/dms/lifecycle Queue)

```json
{
  "action": "add_path",
  "file_hash": "sha256:abc123...",
  "file_path": "/mnt/nas/projekte/kopie/rechnung.pdf",
  "detected_at": "2026-03-12T03:00:00Z"
}
```

```json
{
  "action": "update_path",
  "file_hash": "sha256:abc123...",
  "file_path": "/mnt/nas/projekte/neu/rechnung.pdf",
  "old_paths": ["/mnt/nas/projekte/alt/rechnung.pdf"],
  "detected_at": "2026-03-12T03:00:00Z"
}
```

---

## Tech Design (Solution Architect)

**Scope:** PROJ-21 (Scanner-Erweiterung + Schema) + PROJ-22 (Lifecycle-Workflow) werden zusammen designed, da Scanner und Lifecycle-Workflow eine Producer-Consumer-Einheit bilden.

---

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                 HOURLY SCANNER (existing)                 │
│                  alice-dms-scanner                        │
│                                                           │
│  For each file on NAS:                                    │
│  1. Compute SHA-256 hash                                  │
│  2. Lookup hash in Redis → detect lifecycle event         │
│  3. Route to appropriate queue                            │
└────────────┬──────────────┬──────────────────────────────┘
             │              │
    NEW FILE  │    LIFECYCLE │ EVENT (Fall 1 or Fall 2)
             ↓              ↓
    ┌─────────────┐  ┌──────────────────────────────────┐
    │  Extractor  │  │    MQTT: alice/dms/lifecycle      │
    │   Queues    │  │   (new queue, skip extractors)    │
    │ (existing)  │  └──────────────┬───────────────────┘
    └──────┬──────┘                 │
           │                        ↓
           ↓              ┌─────────────────────┐
    ┌────────────┐        │ alice-dms-lifecycle  │  ← NEW WORKFLOW
    │   nightly  │        │  (MQTT subscriber,   │    (PROJ-22)
    │  Processor │        │   event-driven,      │
    │ (existing) │        │   no LLM)            │
    └──────┬─────┘        └──────────┬──────────┘
           │                         │
           └────────────┬────────────┘
                        ↓
              ┌─────────────────────┐
              │       Weaviate      │
              │  (6 collections,    │
              │  + additional_paths)│
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │        Redis        │
              │  path_to_hash       │
              │  hash_to_paths:<h>  │
              └─────────────────────┘
```

---

### Component 1: Scanner Lifecycle Detection (PROJ-21)

**What changes in `alice-dms-scanner`:**

After computing the file hash, the scanner checks Redis before routing. This adds one decision tree to the existing scanner loop:

```
Per-file Decision Tree (new logic):
─────────────────────────────────────────────────────────
Hash known? (check path_to_hash by file_path)
│
├─ NO → Normal path (new file → extractor queue, as today)
│
└─ YES (same path, different hash)
   → Fall 3: File content changed
     Action: queue with action=replace + old_hash
             Remove old hash from alice:dms:processed

Hash known? (check hash_to_paths by hash)
│
├─ Hash in processed? → Check if all known paths exist on NAS
│   ├─ ALL paths still exist → Fall 1: Duplicate copy
│   │   Action: publish add_path to alice/dms/lifecycle
│   └─ NO paths exist anymore → Fall 2: File moved
│       Action: publish update_path to alice/dms/lifecycle
│
└─ No entry in hash_to_paths → treat as new file
```

**NAS path existence check:**
The scanner already has NAS access (mounted filesystem in n8n container). For each hash in `hash_to_paths`, the scanner checks if the file path still resolves on disk. This is a simple filesystem stat call — no network overhead beyond what the scanner already does.

---

### Component 2: Weaviate Schema Extension (PROJ-21)

**What changes in all 6 Weaviate collections:**

A single new field is added to every collection:

| New Field | Type | Purpose |
|---|---|---|
| `additional_paths` | String[] | Stores all known file paths that point to the same document content |

`original_path` remains the canonical primary path. `additional_paths` grows as duplicates are found.

This is a **backwards-compatible extension** — existing entries work without `additional_paths` (defaults to empty array).

> **Deployment note:** Weaviate supports adding new properties to existing collections without data loss. No collection recreation needed.

---

### Component 3: MQTT Lifecycle Queue (PROJ-21 → PROJ-22 bridge)

**New MQTT topic: `alice/dms/lifecycle`**

Two message types flow through this queue:

```
add_path message:
  - action: "add_path"
  - file_hash: SHA-256 of the duplicate file
  - file_path: new path where duplicate was found
  - detected_at: timestamp

update_path message:
  - action: "update_path"
  - file_hash: SHA-256 of the moved file
  - file_path: new path after move
  - old_paths: list of old paths that no longer exist
  - detected_at: timestamp
```

Fall 3 (content change) does **not** go through this queue — it goes directly to the extractor queues, same as a new file, but with `action: replace` to signal the processor to delete the old Weaviate entry first.

---

### Component 4: alice-dms-lifecycle Workflow (PROJ-22)

**New workflow — entirely event-driven, no LLM.**

```
Workflow structure:
──────────────────────────────────────────────────────────
MQTT Trigger: alice/dms/lifecycle (QoS 1)
  ↓
Parse & validate incoming message
  ↓
Switch: action == ?
  ↓                           ↓
"add_path"               "update_path"
  ↓                           ↓
Search Weaviate          Search Weaviate
(all 6 collections,      (all 6 collections,
 by file_hash)            by file_hash)
  ↓                           ↓
PATCH Weaviate:          PATCH Weaviate:
append file_path         set original_path = new path
to additional_paths[]
  ↓                           ↓
Redis update:            Redis update:
HSET path_to_hash        HDEL old paths from path_to_hash
SADD hash_to_paths       HSET new path in path_to_hash
                         SREM old paths from hash_to_paths
                         SADD new path to hash_to_paths
  ↓                           ↓
MQTT: alice/dms/done     MQTT: alice/dms/done
──────────────────────────────────────────────────────────
```

**Weaviate search strategy:** The workflow searches all 6 collections sequentially until it finds the object by `file_hash`. This is at most 6 API calls, all lightweight GraphQL queries. Once found, a single PATCH request updates the object.

**Error handling:**
- Weaviate object not found → log warning, update Redis anyway (resilient)
- Weaviate PATCH fails → publish to `alice/dms/error`, skip Redis updates (consistent)
- Redis unreachable → log error, publish to `alice/dms/error` with note on inconsistent state
- Unknown action → discard message, log warning

---

### Redis Data Model

Both `path_to_hash` and `hash_to_paths` are populated by PROJ-19 (Processor) and kept in sync by PROJ-22 (Lifecycle). Scanner reads them; Lifecycle writes to them.

| Redis Key | Type | Populated by | Read by |
|---|---|---|---|
| `alice:dms:path_to_hash` | Hash | Processor (PROJ-19) + Lifecycle (PROJ-22) | Scanner (PROJ-21) |
| `alice:dms:hash_to_paths:<hash>` | Set | Processor (PROJ-19) + Lifecycle (PROJ-22) | Scanner (PROJ-21) |
| `alice:dms:processed` | Set | Processor (PROJ-19) | Scanner (PROJ-21) |
| `alice:dms:queued_files` | Set | Scanner | Processor, Lifecycle |

---

### No New Dependencies

All required tools are already available:
- MQTT: `mqtt-alice` credential (existing)
- Redis: `redis-alice` credential (existing)
- Weaviate: HTTP calls via `WEAVIATE_URL` env var (existing pattern from PROJ-19)
- NAS access: already mounted in n8n container (used by scanner since PROJ-16)

---

### Implementation Scope

| Component | Workflow/File | Change Type |
|---|---|---|
| Scanner lifecycle detection | `alice-dms-scanner` | Extend (new decision tree in existing loop) |
| Weaviate schema `additional_paths` | All 6 `schemas/*.json` | Extend (additive, no recreation) |
| Lifecycle workflow | `alice-dms-lifecycle` (new) | Create |
| Processor: Fall 3 routing | `alice-dms-processor` | Minor extend (handle `action=replace`) |

---

<!-- Sections below are added by subsequent skills -->

## QA Test Results

### Re-Test #1 (2026-03-13)

**Tested:** 2026-03-13
**Scope:** Re-test after bug fixes. Static code review of workflow JSON, schema files, and scanner logic (no browser UI -- backend-only feature)
**Tester:** QA Engineer (AI)
**Trigger:** Fixes applied for BUG-1, BUG-2, BUG-4, BUG-7 from initial test

### Bug Fix Verification

#### BUG-1 (High): Fall 3 replace action not passed to extractor MQTT messages -- VERIFIED FIXED
- [x] All four extractor MQTT publish nodes (PDF, OCR, TXT, Office) now include `action: $json._lifecycle_action === 'replace' ? 'replace' : 'new'` and `old_hash: $json._old_hash || null`
- [x] `Code: Stability Check` merges lifecycle fields from both `Code: Hash + Size` and `Code: Lifecycle Check` via `{ ...hashItem, ...lifecycleItem }`
- [x] Fields `_lifecycle_action` and `_old_hash` propagate correctly through the stability check and type routing pipeline

#### BUG-2 (Medium): Stale queued_files entries on Fall 3 replace -- VERIFIED FIXED
- [x] `Code: Mark Queued` now checks `if (item._lifecycle_action === 'replace' && item._old_hash)` and calls `client.sRem('alice:dms:queued_files', item._old_hash)` before adding the new hash
- [x] Comment in code references the BUG-2 fix explicitly

#### BUG-4 (Critical): GraphQL injection via file_hash -- VERIFIED FIXED
- [x] `Code: Weaviate Find by Hash` in `alice-dms-lifecycle.json` now sanitizes: `const fileHash = String(rawHash).replace(/[^a-zA-Z0-9:]/g, '')`
- [x] Logs a warning when sanitization modifies the input value
- [x] Throws an error if the sanitized hash is empty (prevents empty-string queries)
- [x] Regex correctly allows SHA-256 hash format `sha256:<hex>` while stripping GraphQL-dangerous characters (`"`, `}`, `{`, `#`, etc.)

#### BUG-7 (Medium): Missing MQTT error handler -- VERIFIED FIXED
- [x] `Error Trigger` node added (ID: `lifecycle-error-trigger-01-alice-dms-lifecycle-v1`)
- [x] `Code: Format Error` node extracts error message, last node executed, execution ID, and timestamp
- [x] `MQTT: Publish Error` node publishes to `alice/dms/error` with QoS 1
- [x] Connection chain is correct: Error Trigger -> Code: Format Error -> MQTT: Publish Error
- [ ] BUG-9: NEW -- Error Trigger requires `errorWorkflow` setting in workflow settings to point to this workflow's own ID. Without this setting, the Error Trigger node will never fire. (See BUG-9 below)

### Acceptance Criteria Status (re-verified)

#### AC-1: Scanner -- path_to_hash Lookup per file (HGET with file_path)
- [x] `Code: Lifecycle Check` performs `client.hGet('alice:dms:path_to_hash', filePath)` after hash computation
- [x] No entry found and hash not in `processed`: returns `_lifecycle_action: 'new'`
- [x] Entry found and hash matches: returns `_lifecycle_action: 'already_processed', _skip: true`

#### AC-2: Fall 3 (File content changed) -- same path, different hash
- [x] Lifecycle Check detects `knownHashForPath !== currentHash` and returns `_lifecycle_action: 'replace'` with `_old_hash`
- [x] Old hash removed from `alice:dms:processed` via `client.sRem`
- [x] `action` and `old_hash` included in all extractor MQTT messages (BUG-1 fix verified)
- [x] Old hash removed from `queued_files` on Fall 3 replace (BUG-2 fix verified)

#### AC-3: Fall 1 (Duplicate) -- hash known, all paths still exist on NAS
- [x] Lifecycle Check detects hash in `processed`, retrieves `hash_to_paths`, checks NAS file existence
- [x] When all existing paths still resolve, returns `_lifecycle_action: 'add_path'`
- [x] Dead paths are cleaned from `hash_to_paths` during duplicate detection

#### AC-4: Fall 2 (Move) -- hash known, no paths exist on NAS anymore
- [x] When no existing paths resolve on NAS, returns `_lifecycle_action: 'update_path'` with `_old_paths`

#### AC-5: Falls 1 and 2 route to alice/dms/lifecycle queue (no extractor)
- [x] `MQTT: Publish Lifecycle` node publishes to `alice/dms/lifecycle` topic
- [x] Lifecycle events go to the `false` branch of `IF: Is Lifecycle Event` (not `new`/`replace`), bypassing extractors
- [x] Message format matches spec: includes `action`, `file_hash`, `file_path`, `detected_at`
- [x] `update_path` message includes `old_paths` array
- [x] QoS 1 configured on lifecycle MQTT publish

#### AC-6: Weaviate Schema -- additionalPaths field on all 6 collections
- [x] All 6 collections (Invoice, BankStatement, Document, Email, SecuritySettlement, Contract) have `additionalPaths` (text[], non-indexed, non-vectorized)
- [x] `filePath` remains as primary field in all collections

### Edge Cases Status

#### EC-1: Mixed state (some paths exist, some do not)
- [x] Handled correctly: treated as Fall 1 (add_path), dead paths removed from hash_to_paths

#### EC-2: hash_to_paths empty despite hash in processed
- [x] Handled correctly: `knownPaths.length === 0` returns `_lifecycle_action: 'new'`

#### EC-3: NAS path check failure
- [x] `try { fs.accessSync(p, fs.constants.F_OK); return true; } catch(e) { return false; }` catches all error types (ENOENT, EACCES, etc.)

#### EC-4: Multiple moves in sequence
- [x] Each scan cycle independently checks `hash_to_paths` and `path_to_hash`, so sequential moves produce correct lifecycle events

### Security Audit Results

- [x] No secrets hardcoded -- Redis password read from `$env.REDIS_PASSWORD` with try/catch fallback
- [x] No user-facing endpoints exposed -- scheduled internal workflow
- [x] Credential IDs verified correct (mqtt-alice: Kqy6cn7hyDDXrBA0)
- [x] GraphQL injection mitigated -- file_hash sanitized with `/[^a-zA-Z0-9:]/g` (BUG-4 fix verified)
- [x] No external network calls beyond internal Docker network (weaviate:8080, redis:6379)
- [x] MQTT topics internal only (alice/dms/*), no auth bypass surface
- [x] Weaviate PATCH URL construction uses class names from hardcoded list and IDs from Weaviate's own response -- no injection vector

### New Bugs Found (Re-Test)

#### BUG-9: Lifecycle workflow Error Trigger requires errorWorkflow setting to activate
- **Severity:** Medium
- **Steps to Reproduce:**
  1. The `alice-dms-lifecycle` workflow includes an Error Trigger node and Error Trigger -> Format Error -> MQTT: Publish Error chain
  2. n8n's Error Trigger node only fires when the workflow's settings include `"errorWorkflow": "<this-workflow-id>"`
  3. Current workflow settings: `{ "executionOrder": "v1" }` -- no `errorWorkflow` configured
  4. Expected: Error handler chain fires on Weaviate/Redis failures and publishes to `alice/dms/error`
  5. Actual: Error handler chain is dead code -- will never execute until `errorWorkflow` is set post-deploy
- **Impact:** The BUG-7 fix is structurally correct (nodes + connections exist) but will not function until the workflow is imported to n8n and the `errorWorkflow` setting is configured. The sticky note does mention "Post-Deploy: Error Workflow Config" but this is easy to overlook.
- **Priority:** Add to deployment checklist. The workflow JSON cannot include the setting pre-deploy because the workflow ID is assigned by n8n on import.

#### BUG-6 (carried over): Redis nodes use `require('redis')` with hardcoded host
- **Severity:** Medium
- **Status:** Still present (pre-existing pattern from PROJ-19, not addressed in this fix cycle)
- **Priority:** Fix in next sprint

### Previously Reported Bugs -- Final Status

| Bug | Severity | Status |
|-----|----------|--------|
| BUG-1 | High | FIXED and verified |
| BUG-2 | Medium | FIXED and verified |
| BUG-3 | N/A | Withdrawn (false alarm) |
| BUG-4 | Critical | FIXED and verified |
| BUG-5 | N/A | Withdrawn (spec terminology, not code bug) |
| BUG-6 | Medium | Carried over (pre-existing, deferred) |
| BUG-7 | Medium | FIXED (structurally), limited by BUG-9 |
| BUG-8 | N/A | Withdrawn (matches spec) |
| BUG-9 | Medium | NEW -- errorWorkflow setting not in JSON |

### Summary
- **Acceptance Criteria:** 15/15 passed
- **Previous Bugs Fixed:** 4/4 verified (BUG-1, BUG-2, BUG-4, BUG-7)
- **New Bugs Found:** 1 (BUG-9, Medium -- deployment config, not a code defect)
- **Carried Over:** 1 (BUG-6, Medium -- pre-existing pattern, deferred)
- **Security:** All previous findings resolved. No new security issues.
- **Production Ready:** YES (conditional)
- **Conditions:** BUG-9 must be addressed during deployment (set errorWorkflow in n8n UI after import). BUG-6 is accepted as pre-existing technical debt.

## Deployment

**Deployed:** 2026-03-14

### Deployed Artifacts
- `workflows/core/alice-dms-scanner.json` — lifecycle detection + routing (Fall 1/2/3)
- `workflows/core/alice-dms-lifecycle.json` — MQTT consumer for `alice/dms/lifecycle`
- Weaviate schema extended: `additionalPaths` field added to all 6 collections

### Post-Deploy Action Required
After importing `alice-dms-lifecycle` into n8n, configure:
**Settings → Error Workflow → select `alice-dms-lifecycle`** (points the error handler to itself so the Error Trigger node activates on execution failures).
