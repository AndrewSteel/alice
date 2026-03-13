# PROJ-21: DMS Lifecycle Management (Duplikate, Verschiebungen, Dateiänderungen)

## Status: In Progress
**Created:** 2026-03-12
**Last Updated:** 2026-03-13

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
_To be added by /qa_

## Deployment
_To be added by /deploy_
