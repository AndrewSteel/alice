# PROJ-4: HA Auto-Sync (MQTT → n8n → Weaviate)

## Status: Deployed

**Created:** 2026-02-23
**Last Updated:** 2026-02-26
**Deployed:** 2026-02-26

## Dependencies

- Requires: PROJ-1 (HA Intent Infrastructure) — `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` must exist ✅ Deployed
- Requires: PROJ-2 (FastAPI Intent Helper) — templates with `{name}`/`{area}` placeholders must be populated ✅ Deployed
- Requires: PROJ-3 (HA-First Chat Handler) — Weaviate `HAIntent` collection must be in use ✅ Deployed

## Overview

Keeps the Weaviate `HAIntent` collection automatically in sync with Home Assistant. When HA starts, a new entity is added, or an entity is removed, an MQTT message triggers an n8n workflow that fetches the current entity registry, diffs it against `alice.ha_entities`, generates utterances using the stored templates, and updates Weaviate accordingly. New HA devices automatically become speakable within 60 seconds.

The MQTT topic `alice/ha/sync` is shared with PROJ-2 (hassil-parser). The workflow must handle all event types published to this topic.

## User Stories

- As Andreas, I want a new smart home device to be controllable via Alice immediately after adding it to HA so that I never have to manually update intent lists.
- As Andreas, I want removed or renamed entities to stop matching in Alice so that I don't get errors for devices that no longer exist.
- As a developer, I want a full sync to run when HA restarts so that the system recovers automatically after HA updates.
- As a developer, I want every sync run logged in `alice.ha_sync_log` so that I can see what changed and debug failures.
- As a developer, I want to be able to trigger a manual full sync via MQTT so that I can force a refresh during development.
- As a developer, I want the sync to re-run automatically after hassil-parser updates the templates so that new German utterances are immediately used for all entities.

## Acceptance Criteria

### MQTT Events (published by HA automations)

- [ ] Home Assistant automation `alice_sync_on_start` publishes `{"event": "ha_start", "sync_type": "full"}` to `alice/ha/sync` 30 seconds after HA start
- [ ] Home Assistant automation `alice_sync_on_entity_created` publishes `{"event": "entity_created", "entity_id": "..."}` to `alice/ha/sync` 5 seconds after entity registry update with action `create`
- [ ] Home Assistant automation `alice_sync_on_entity_removed` publishes `{"event": "entity_removed", "entity_id": "..."}` to `alice/ha/sync` immediately after entity registry update with action `remove`

### n8n Workflow: Event Routing

- [ ] n8n workflow `alice-ha-intent-sync` is triggered by MQTT topic `alice/ha/sync`
- [ ] Workflow handles all four event types on `alice/ha/sync`:
  - `ha_start` → trigger full sync
  - `entity_created` → trigger incremental sync for that entity_id
  - `entity_removed` → trigger removal for that entity_id
  - `templates_updated` (published by PROJ-2 hassil-parser after GitHub import) → trigger full sync to apply new patterns to all existing entities
- [ ] Unknown event types are logged and ignored (no crash)

### Full Sync Logic

- [ ] Workflow fetches all states from HA `GET /api/states` and area registry from HA `GET /api/config/area_registry/list`
- [ ] Workflow diffs fetched entities against `alice.ha_entities` to find: added, removed, updated (friendly_name or area change)
- [ ] For each **added/updated** entity: generate utterances from matching templates in `alice.ha_intent_templates` using `{name}` → `friendly_name` + `aliases`, `{area}` → `area_name`, `{where}` → both area and name variants
- [ ] Generated utterances are batch-inserted (max 100 per batch) into Weaviate `HAIntent` collection with field `entityId` (camelCase, matching `schemas/ha-intent.json`)
- [ ] For each **removed** entity: all Weaviate objects with `entityId = entity_id` are deleted via Weaviate `where` filter
- [ ] `alice.ha_entities` table is updated to reflect current state after each sync (upsert on `entity_id`)

### Logging & Timing

- [ ] `alice.ha_sync_log` entry created at start with `status = 'running'`; updated at end with `status = 'success'`, `'partial'`, or `'error'`
- [ ] `sync_type` column reflects the trigger: `'full'` for ha_start and templates_updated events, `'incremental'` for entity_created/removed
- [ ] Sync completes in < 30 seconds for a full sync of up to 200 entities
- [ ] New entity becomes matchable in PROJ-3 intent detection within 60 seconds of being added to HA

## Edge Cases

- **HA API unreachable during sync**: log error in `ha_sync_log`, set status to `error`, do not corrupt existing Weaviate data.
- **Entity has no `friendly_name`**: use `entity_id` parts as fallback name (e.g. `light.wohnzimmer_decke` → "wohnzimmer decke").
- **Entity has no area assigned**: only generate name-based utterances (no area variants).
- **No templates for domain**: if `alice.ha_intent_templates` has no active rows for a domain, skip intent generation for that entity and log a warning. (Note: PROJ-2 must be run first to populate templates; PROJ-1 seeds only 8 fallback domains.)
- **Duplicate `friendly_name` across areas**: generate utterances for both; disambiguation handled by Weaviate certainty scores in PROJ-3.
- **No-op incremental**: MQTT `entity_created` arrives for an already-synced entity with no changes — detect via comparison of `friendly_name`, `area_id`, `aliases` against `alice.ha_entities` and skip Weaviate update.
- **Weaviate batch insert partially fails**: log failed objects, continue with the rest, mark sync as `partial` in `ha_sync_log`.
- **Concurrent sync conflict**: if `alice.ha_sync_log` has an entry with `status = 'running'` and `started_at > NOW() - INTERVAL '5 minutes'`, skip the new trigger and log a warning. (Stale `running` entries older than 5 minutes are treated as crashed and overwritten.)
- **`templates_updated` arrives while full sync is running**: treat as concurrent conflict (see above) — the already-running full sync will use the updated templates since it reads from `alice.ha_intent_templates` at start time; no additional sync needed.

## Technical Requirements

- HA automations written in YAML, committed to `docs/ha-automations/` as reference
- n8n workflow exported as JSON to `workflows/core/alice-ha-intent-sync.json` (consistent with PROJ-3 path `workflows/core/`)
- Batch size for Weaviate inserts: max 100 objects per batch
- Weaviate field name for entity reference: `entityId` (camelCase, as defined in `schemas/ha-intent.json`)
- Supported domains for intent generation: `light`, `switch`, `cover`, `media_player`, `climate`, `scene`, `lock`, `alarm_control_panel`, `vacuum`
  - Note: `vacuum` domain is seeded in PROJ-1 (`ha_intent_infrastructure.sql`) and must be included
- MQTT credential in n8n: same credential used for PROJ-2 and validated in PROJ-1 deployment (topic `alice/ha/sync` confirmed reachable)
- HA REST API credential in n8n: same `HA_URL` / `HA_TOKEN` env vars used in PROJ-3 (`alice-tool-ha` workflow)

---

## Tech Design (Solution Architect)

### Systemüberblick

Das Feature verbindet drei bereits existierende Systeme zu einer automatischen Sync-Pipeline: Home Assistant (Quelle) → MQTT (Ereignisbus) → n8n (Logik) → PostgreSQL + Weaviate (Datenhaltung).

### A) Komponenten-Struktur

```text
Home Assistant
+-- Automation: alice_sync_on_start          (30s nach HA-Start → ha_start)
+-- Automation: alice_sync_on_entity_created (5s nach entity add → entity_created)
+-- Automation: alice_sync_on_entity_removed (sofort nach entity remove → entity_removed)
        ↓ MQTT Publish: alice/ha/sync

MQTT Broker (alice/ha/sync topic)
        ↓ Trigger

n8n Workflow: alice-ha-intent-sync
+-- [1] MQTT Trigger Node
+-- [2] Event Router (Switch)
|   +-- ha_start           → [Full Sync Branch]
|   +-- entity_created     → [Incremental Sync Branch]
|   +-- entity_removed     → [Remove Branch]
|   +-- templates_updated  → [Full Sync Branch]
|   +-- unknown            → [Log & Stop]
|
+-- [Full Sync Branch]
|   +-- Conflict Check (ha_sync_log running?)
|   +-- Create ha_sync_log (status: running)
|   +-- HTTP: GET /api/states (HA)
|   +-- HTTP: GET /api/config/area_registry/list (HA)
|   +-- Diff gegen alice.ha_entities (PostgreSQL)
|   +-- Utterance-Generierung aus alice.ha_intent_templates
|   +-- Weaviate Batch Insert (max 100/Batch)
|   +-- Weaviate Delete (entfernte Entities)
|   +-- Upsert alice.ha_entities
|   +-- Update ha_sync_log (status: success/partial/error)
|
+-- [Incremental Sync Branch]
|   +-- Conflict Check
|   +-- Create ha_sync_log (status: running, sync_type: incremental)
|   +-- HTTP: GET /api/states/{entity_id} (HA)
|   +-- Vergleich mit alice.ha_entities (no-op Erkennung)
|   +-- Utterance-Generierung für einzelne Entity
|   +-- Weaviate Insert
|   +-- Upsert alice.ha_entities
|   +-- Update ha_sync_log
|
+-- [Remove Branch]
    +-- Weaviate Delete (entityId = entity_id)
    +-- Delete aus alice.ha_entities
    +-- ha_sync_log Entry
```

### B) Datenmodell

**PostgreSQL `alice.ha_entities`** (PROJ-1, vorhanden):

- Aktuelle Kopie aller HA-Entities (entity_id, friendly_name, area_id, domain, aliases)
- Dient als "letzter bekannter Stand" für Diff-Berechnung

**PostgreSQL `alice.ha_sync_log`** (PROJ-1, vorhanden):

- Pro Sync-Lauf: wann, welcher Typ (full/incremental), Anzahl betroffener Entities, Status (running/success/partial/error)
- Crasherkennung: Einträge mit `status = 'running'` älter als 5 Min gelten als abgestürzt

**Weaviate `HAIntent`** (PROJ-1/3, vorhanden):

- Pro Entity: mehrere Utterance-Objekte (z.B. "Wohnzimmerlicht einschalten")
- Felder: `utterance` (vektorisiert), `entityId`, `domain`, `service`, `parameters`, `language`, `intentTemplate`, `certaintyThreshold`
- Löschen: alle Objekte mit passendem `entityId` via Where-Filter

**Keine neuen Schemas nötig** — alle drei Datenspeicher existieren bereits.

### C) Technische Entscheidungen

| Entscheidung | Gewählt | Warum |
| --- | --- | --- |
| Trigger-Mechanismus | MQTT | HA hat nativen MQTT-Support; kein Polling; gleicher Broker wie PROJ-2 |
| Workflow-Engine | n8n (neuer Workflow) | Konsistent mit PROJ-2/3; separater Workflow (Single Responsibility) |
| Conflict-Guard | PostgreSQL `ha_sync_log` | Bereits vorhanden; verhindert parallele Full-Syncs ohne externe Locks |
| Batch-Größe Weaviate | Max 100 Objekte | Weaviate-Empfehlung für stabile Batch-Performance |
| Utterance-Generierung | In n8n (Code Node) | Templates in DB; Platzhalter `{name}`, `{area}`, `{where}` zur Laufzeit ersetzt |
| Fallback für fehlenden Namen | entity_id-Teile | `light.wohnzimmer_decke` → "wohnzimmer decke" — deterministisch, kein LLM nötig |
| HA Automations | YAML in `docs/ha-automations/` | Referenz-Dokumentation; manuell in HA eingespielt |

### D) Neue Dateien

| Datei | Typ | Beschreibung |
| --- | --- | --- |
| `workflows/core/alice-ha-intent-sync.json` | n8n Workflow | Hauptworkflow (MQTT Trigger → Sync-Logik) |
| `docs/ha-automations/alice_sync_on_start.yaml` | HA Automation | Publiziert `ha_start` 30s nach HA-Start |
| `docs/ha-automations/alice_sync_on_entity_created.yaml` | HA Automation | Publiziert `entity_created` bei neuer Entity |
| `docs/ha-automations/alice_sync_on_entity_removed.yaml` | HA Automation | Publiziert `entity_removed` bei Entfernung |

**Keine neuen npm-Pakete oder Docker-Container** — alle Abhängigkeiten existieren bereits.

### E) Schnittstellen zu bestehenden Features

- **PROJ-2 (hassil-parser)**: publiziert `templates_updated` auf demselben MQTT-Topic → löst Full Sync aus, sodass neue Utterances sofort für alle Entities gelten
- **PROJ-3 (Chat Handler)**: liest `HAIntent` aus Weaviate — profitiert automatisch von aktualisierten Utterances; keine Änderung am Chat-Workflow nötig

## QA Test Results

**Tested:** 2026-02-26
**Artifacts Reviewed:** `workflows/core/alice-ha-intent-sync.json`, `docs/ha-automations/*.yaml`, `schemas/ha-intent.json`
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: MQTT Events (HA Automations)

- [x] `alice_sync_on_start` publishes `{"event": "ha_start", "sync_type": "full"}` to `alice/ha/sync` 30s after HA start -- file `docs/ha-automations/alice_sync_on_start.yaml` uses `platform: homeassistant` event `start`, 30s delay, correct topic, QoS 1, retain false. Payload includes `timestamp` (extra field, acceptable).
- [x] `alice_sync_on_entity_created` publishes `{"event": "entity_created", "entity_id": "..."}` to `alice/ha/sync` 5s after entity registry update (action: create) -- correct trigger, 5s delay, mode queued max 10.
- [x] `alice_sync_on_entity_removed` publishes `{"event": "entity_removed", "entity_id": "..."}` to `alice/ha/sync` immediately (no delay) on entity registry update (action: remove) -- correct.

#### AC-2: n8n Workflow Event Routing

- [x] Workflow `alice-ha-intent-sync` is triggered by MQTT topic `alice/ha/sync` -- MQTT Trigger node subscribes to `alice/ha/sync`.
- [ ] **BUG (BUG-1, Critical):** Workflow does NOT correctly handle all four event types. The Switch node defines 4 separate rules but in n8n Switch v3, each rule produces a separate output index. `ha_start` (rule 0) and `templates_updated` (rule 1) both have outputKey `full_sync` but occupy separate output indices. The connections map only 4 outputs (0-3), so `templates_updated` (output 1) is routed to `Incr Sync: Conflict Check` instead of `Full Sync: Conflict Check`. Similarly, `entity_created` (output 2) goes to `Remove: Delete from Weaviate` and `entity_removed` (output 3) goes to `Log Unknown Event`. The fallback (output 4) has no connection at all.
- [ ] **BUG (BUG-2, Critical):** Unknown event types are NOT routed to `Log Unknown Event`. The fallback output (index 4) is unmapped in the connections object. Unknown events silently drop.

#### AC-3: Full Sync Logic

- [ ] **BUG (BUG-3, Critical):** The full sync code node "Full Sync: Generate Utterances" contains a JavaScript syntax error: `const hassil Templates = Object.keys(templates)` -- the variable name `hassil Templates` has a space, making it an invalid JavaScript identifier. This will throw a `SyntaxError` at runtime, crashing the entire full sync branch. No entities will be synced.
- [x] Workflow fetches entity registry via `GET /api/config/entity_registry/list` and area registry via `GET /api/config/area_registry/list` -- implemented in "Full Sync: Fetch Exposed Entities (WS)" code node.
- [x] Workflow diffs fetched entities against `alice.ha_entities` -- "Full Sync: Diff vs DB" query plus diff logic in Generate Utterances code node identifies added, updated, removed.
- [x] For added/updated entities, utterances are generated from matching templates using `{name}`, `{area}`, `{where}` placeholders -- pattern replacement logic is present (would work if BUG-3 is fixed).
- [x] Batch insert uses max 100 per batch -- `BATCH_SIZE = 100` in "Full Sync: Batch Insert Weaviate" code node.
- [x] Uses `entityId` (camelCase) matching `schemas/ha-intent.json` -- confirmed.
- [x] Removed entities are deleted from Weaviate via `where` filter on `entityId` -- "Full Sync: Delete Weaviate (updated+removed)" code node.
- [x] `alice.ha_entities` is updated via upsert -- "Full Sync: Execute PG Upsert" node with ON CONFLICT DO UPDATE.

#### AC-4: Logging & Timing

- [x] `ha_sync_log` entry created at start with `status = 'running'` -- "Full Sync: Create Log (running)" node.
- [x] Updated at end with `status = 'success'`, `'partial'`, or `'error'` -- "Full Sync: Update Log (complete)" node uses `final_status` derived from batch errors.
- [x] `sync_type` reflects trigger -- full sync uses `'full'`, incremental uses `'incremental'`.
- [ ] **Cannot verify** < 30 second timing or 60 second end-to-end latency without live deployment. Deferred to deployment testing.

### Edge Cases Status

#### EC-1: HA API unreachable during sync
- [ ] **BUG (BUG-4, High):** If the HA API fetch fails in "Full Sync: Fetch Exposed Entities (WS)", the code node throws an error (`throw new Error(...)`). However, no error handler/catch node exists in the workflow. n8n will mark the execution as failed, but the `ha_sync_log` entry remains stuck at `status = 'running'` forever (since the log-complete node is never reached). The conflict guard treats entries older than 5 minutes as stale, so it will eventually recover, but the log is inaccurate.

#### EC-2: Entity has no friendly_name
- [x] Fallback uses entity_id parts: `entity.entity_id.split('.').slice(1).join(' ').replace(/_/g, ' ')` -- correctly converts `light.wohnzimmer_decke` to `wohnzimmer decke`.

#### EC-3: Entity has no area assigned
- [x] Only name-based utterances generated when `area_name` is null -- pattern replacement logic skips area variants when `area` is null.

#### EC-4: No templates for domain
- [x] Skipped with console.log warning -- `if (allTemplates.length === 0)` returns empty array and logs warning.

#### EC-5: Duplicate friendly_name across areas
- [x] Utterances generated for both entities independently -- each entity generates its own utterances.

#### EC-6: No-op incremental
- [x] Comparison of `friendly_name`, `area_id`, `aliases` against existing DB record -- if no change detected, logs "no change detected" and returns `skip_reason: 'no_change'`.
- [ ] **BUG (BUG-5, Medium):** The no-op check in incremental sync compares `area_id` but not `area_name`. If an area is renamed (same `area_id`, different `area_name`), the no-op check will not detect the change and skip the update.

#### EC-7: Weaviate batch insert partially fails
- [x] Failed objects are logged, status set to `'partial'` if some succeed, `'error'` if all fail -- batch error tracking in "Full Sync: Batch Insert Weaviate" code node.

#### EC-8: Concurrent sync conflict
- [x] Conflict check queries `ha_sync_log` for `status = 'running'` entries newer than 5 minutes -- "Full Sync: Conflict Check" and "Incr Sync: Conflict Check" nodes.
- [ ] **BUG (BUG-6, Medium):** The incremental sync conflict check only looks for `sync_type = 'incremental'` running entries (`WHERE status = 'running' AND sync_type = 'incremental'`). It does NOT check for a running full sync. Per the spec, concurrent syncs of any type should be blocked. An incremental sync could run concurrently with a full sync, potentially causing race conditions on Weaviate data.

#### EC-9: templates_updated during full sync
- [ ] **Partially handled:** The conflict guard should prevent this, but see BUG-1 -- `templates_updated` is currently routed to the wrong branch entirely.

### Security Audit Results

#### SEC-1: SQL Injection via MQTT payload
- [ ] **BUG (BUG-7, Critical):** Multiple SQL queries use direct string interpolation of values from MQTT payloads without parameterization or sanitization:
  - `Remove: Deactivate in PG`: `WHERE entity_id = '{{ $json.entity_id }}'` -- an attacker who publishes `{"event": "entity_removed", "entity_id": "'; DROP TABLE alice.ha_entities; --"}` to `alice/ha/sync` can execute arbitrary SQL.
  - `Incr Sync: PG Upsert Entity`: `'{{ $json.entity.friendly_name }}'` and others -- if HA returns a friendly_name containing SQL metacharacters (e.g., a single quote), the query will break or be exploitable.
  - `Incr Sync: Load Templates`: `domain = '{{ ... }}'` -- injectable via entity domain.
  - `Incr Sync: Check Existing in DB`: `entity_id = '{{ ... }}'` -- injectable.
  - `Full Sync: Update Log (complete)`: `status = '{{ $json.final_status }}'` -- injectable if the status string is manipulated.
  - `Full Sync: Execute PG Upsert`: The entire JSON blob is interpolated into a `DO $$` block -- arbitrary SQL via crafted entity data.
  - **Mitigation note:** Access to the MQTT broker is VPN-only and the topic requires HA automation or developer access. However, any compromised HA instance or MQTT client on the VPN can exploit this. **Severity remains Critical** because it enables full database takeover.

#### SEC-2: No MQTT payload schema validation
- [ ] **BUG (BUG-8, High):** The "Parse MQTT Message" node does basic JSON parsing but performs no schema validation. There is no check that `event` is one of the expected values before routing, no type check on `entity_id`, no length limits. The Switch node handles known events but the fallback path for unknown events has no connection (BUG-2), meaning malformed payloads could cause unpredictable behavior.

#### SEC-3: No authentication on Weaviate API calls
- [x] **Acceptable risk:** Weaviate runs on internal Docker network without authentication, consistent with the existing architecture (VPN-only access). No change from PROJ-1/3.

#### SEC-4: HA Token exposure
- [x] HA token read from `process.env.HA_TOKEN` -- not hardcoded. Consistent with PROJ-3 approach.

#### SEC-5: Error messages may leak internal details
- [ ] **BUG (BUG-9, Low):** Error messages include full HA API response codes, Weaviate error text, and internal entity data in `ha_sync_log.error_message` and `details` columns. While this is useful for debugging, if the PostgreSQL database is ever compromised, these logs could reveal internal API structure and error patterns. Acceptable for a VPN-only system but noted for Phase 3 hardening.

### Code Quality Issues

#### CQ-1: Orphan nodes in workflow
- [ ] **BUG (BUG-10, Medium):** Three nodes share position `[3100, 60]`: `full-sync-pg-upsert`, `full-sync-pg-upsert-code`, and `full-sync-pg-upsert-exec`. Only `full-sync-pg-upsert-exec` is connected in the flow. The other two (`full-sync-pg-upsert` and `full-sync-pg-upsert-code`) are orphan nodes that will never execute. They appear to be earlier iterations that were not cleaned up. This does not affect functionality but creates confusion when maintaining the workflow.

#### CQ-2: Node naming inconsistency
- [ ] **BUG (BUG-11, Low):** The node "Full Sync: Fetch Exposed Entities (WS)" references WebSocket in its name but actually uses REST API calls. The code comment even says "We use HTTP long-poll fallback since n8n Code node can't do WebSocket natively." The name is misleading.

#### CQ-3: Hardcoded certainty threshold
- [ ] **BUG (BUG-12, Low):** The value `certaintyThreshold: 0.82` is hardcoded in both the full sync and incremental sync code nodes. This should ideally come from a configuration source (e.g., environment variable or database setting) to allow tuning without workflow modification.

### Bugs Found

#### BUG-1: Event Router miswires templates_updated, entity_created, and entity_removed -- FIXED
- **Severity:** Critical
- **Steps to Reproduce:**
  1. Publish `{"event": "templates_updated"}` to `alice/ha/sync`
  2. Expected: Full Sync branch is triggered
  3. Actual: Incremental Sync branch is triggered (output index 1 maps to Incr Sync in connections)
  4. Similarly, `entity_created` triggers Remove branch, `entity_removed` triggers Log Unknown Event
- **Root Cause:** n8n Switch v3 assigns one output per rule in order. The connections object assumes `ha_start` and `templates_updated` share output 0, but they occupy indices 0 and 1 respectively.
- **Fix:** Merged `ha_start` and `templates_updated` into a single Switch rule using OR combinator. Now: output 0 = full_sync (ha_start OR templates_updated), output 1 = entity_created, output 2 = entity_removed, output 3 = fallback. Connections updated to match.
- **Priority:** Fix before deployment

#### BUG-2: Fallback output for unknown events has no connection -- FIXED
- **Severity:** Critical
- **Steps to Reproduce:**
  1. Publish `{"event": "some_unknown_event"}` to `alice/ha/sync`
  2. Expected: "Log Unknown Event" node runs
  3. Actual: No node runs -- the fallback output (index 4) has no connection in the connections object
- **Fix:** With BUG-1 fix reducing rules from 4 to 3, fallback is now output index 3. Connection added: output 3 -> Log Unknown Event.
- **Priority:** Fix before deployment

#### BUG-3: JavaScript syntax error in Full Sync Generate Utterances -- FIXED
- **Severity:** Critical
- **Steps to Reproduce:**
  1. Trigger a full sync via `{"event": "ha_start"}`
  2. Workflow reaches "Full Sync: Generate Utterances" code node
  3. Expected: Utterances are generated
  4. Actual: `SyntaxError: Unexpected identifier 'Templates'` -- the variable `hassil Templates` (with space) is invalid JavaScript
- **Fix:** Renamed `hassil Templates` to `hassilTemplates` (removed space).
- **Priority:** Fix before deployment

#### BUG-4: ha_sync_log stuck at 'running' when HA API is unreachable -- FIXED
- **Severity:** High
- **Steps to Reproduce:**
  1. Make HA API unreachable (e.g., stop HA)
  2. Trigger full sync via MQTT
  3. "Fetch Exposed Entities" node throws error
  4. Expected: `ha_sync_log` updated to `status = 'error'`
  5. Actual: `ha_sync_log` remains `status = 'running'` until 5-minute stale threshold
- **Fix:** Wrapped HA API calls in try/catch. On error, returns `_ha_error: true` with error details. Added "HA Error Gate" If node that routes errors to a dedicated error logging path (Log HA Error -> Update Log with status='error'). Normal flow continues only when `_ha_error === false`.
- **Priority:** Fix before deployment

#### BUG-5: No-op check ignores area_name changes -- FIXED
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Rename an area in HA (e.g., "Wohnzimmer" to "Stube")
  2. Trigger incremental sync for an entity in that area
  3. Expected: Entity utterances regenerated with new area name
  4. Actual: No-op check compares `area_id` (unchanged) and skips the update
- **Fix:** Added `ex.area_name === entity.area_name` to the no-op comparison in the "Incr Sync: Generate & Insert" code node.
- **Priority:** Fix in next sprint

#### BUG-6: Incremental sync conflict check ignores running full syncs -- FIXED
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Trigger a full sync (ha_start)
  2. While full sync is running, trigger an incremental sync (entity_created)
  3. Expected: Incremental sync is skipped due to conflict
  4. Actual: Incremental sync runs concurrently (its conflict check only looks for `sync_type = 'incremental'`)
- **Fix:** Removed `AND sync_type = 'incremental'` filter from the Incr Sync conflict check query. Now checks for ANY running sync (`WHERE status = 'running' AND started_at > NOW() - INTERVAL '5 minutes'`).
- **Priority:** Fix before deployment

#### BUG-7: SQL injection via MQTT payload in multiple nodes -- FIXED
- **Severity:** Critical
- **Steps to Reproduce:**
  1. Publish to `alice/ha/sync`: `{"event": "entity_removed", "entity_id": "'; DROP TABLE alice.ha_entities; --"}`
  2. Expected: Query safely handles the input
  3. Actual: Arbitrary SQL executed against PostgreSQL
  4. Affected nodes: Remove: Deactivate in PG, Incr Sync: PG Upsert Entity, Incr Sync: Load Templates, Incr Sync: Check Existing in DB, Full Sync: Update Log (complete), Full Sync: Execute PG Upsert
- **Fix:** All 6 affected PostgreSQL nodes converted from n8n expression interpolation to a two-step pattern: (1) Code node builds SQL with proper escaping (single-quote doubling via `replace(/'/g, "''")`, numeric validation, whitelist validation for status values, regex sanitization for entity_id/domain), then (2) Postgres node executes the pre-built query from `$json.query`. Additionally, entity_id format is validated at MQTT ingestion point (BUG-8) using regex `^[a-z_]+\.[a-z0-9_]+$`.
- **Priority:** Fix before deployment

#### BUG-8: No MQTT payload schema validation -- FIXED
- **Severity:** High
- **Steps to Reproduce:**
  1. Publish malformed JSON or JSON with unexpected types to `alice/ha/sync`
  2. Expected: Payload validated, rejected if malformed
  3. Actual: Raw data passed through to downstream nodes
- **Fix:** Parse MQTT Message node now validates: (1) JSON parse with try/catch, (2) payload is an object, (3) `event` is a non-empty string, (4) entity events require `entity_id` as non-empty string matching `^[a-z_]+\.[a-z0-9_]+$` regex. Invalid payloads get `event: '__invalid__'` which routes to the fallback/unknown handler via the Switch node.
- **Priority:** Fix before deployment

#### BUG-9: Error logs may leak internal details -- PARTIALLY FIXED
- **Severity:** Low
- **Steps to Reproduce:**
  1. Trigger a sync that errors (e.g., Weaviate down)
  2. Check `ha_sync_log.error_message` and `details`
  3. Contains full API error text and internal structure
- **Fix (partial):** Error messages and batch errors are now truncated (200 chars per entry, 1000 chars total for error_message, 500 chars for HA error). Full API response bodies are no longer stored. Full hardening deferred to Phase 3.
- **Priority:** Nice to have (Phase 3 hardening)

#### BUG-10: Orphan nodes in workflow JSON -- FIXED
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Open `alice-ha-intent-sync.json` in n8n
  2. Observe 3 nodes stacked at position [3100, 60]
  3. Only `full-sync-pg-upsert-exec` is connected; the other two are orphans
- **Fix:** Removed orphan nodes `full-sync-pg-upsert` (PG Upsert Entities) and `full-sync-pg-upsert-code` (PG Upsert Code). Only the connected `full-sync-pg-upsert-exec` (Execute PG Upsert) remains. The upsert logic was moved to the "Full Sync: Upsert ha_entities" Code node which builds safe SQL.
- **Priority:** Fix in next sprint

#### BUG-11: Misleading node name references WebSocket -- FIXED
- **Severity:** Low
- **Steps to Reproduce:** Open workflow, see "Full Sync: Fetch Exposed Entities (WS)" -- uses REST, not WS.
- **Fix:** Renamed node to "Full Sync: Fetch Exposed Entities (REST)". Updated all connections and node references accordingly.
- **Priority:** Nice to have

#### BUG-12: Hardcoded certaintyThreshold -- FIXED
- **Severity:** Low
- **Steps to Reproduce:** Threshold `0.82` is hardcoded in two places. Cannot be tuned without editing workflow.
- **Fix:** Both full sync and incremental sync code nodes now read `process.env.CERTAINTY_THRESHOLD` with fallback to `0.82`. Threshold can be configured via n8n environment variable without workflow modification.
- **Priority:** Nice to have

### Cross-Browser / Responsive Testing

Not applicable -- PROJ-4 is a backend-only feature (MQTT + n8n workflow + database). No frontend UI components to test.

### Regression Testing

#### PROJ-1 (HA Intent Infrastructure)
- [x] No schema changes required. Existing `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` tables are used as-is.
- [x] Weaviate `HAIntent` collection schema unchanged.

#### PROJ-2 (FastAPI hassil-parser)
- [x] `templates_updated` event integration documented. hassil-parser publishes to same `alice/ha/sync` topic. Workflow handles it (once BUG-1 is fixed).

#### PROJ-3 (HA-First Chat Handler)
- [x] No changes to `alice-chat-handler` workflow. PROJ-3 reads from Weaviate `HAIntent` collection which PROJ-4 populates. No regression risk.

### Summary

- **Acceptance Criteria:** 9/15 passed, 4 failed (BUG-1, BUG-2, BUG-3 block all core functionality), 2 deferred to deployment
- **Bugs Found:** 12 total (4 Critical, 2 High, 3 Medium, 3 Low)
- **Security:** FAIL -- SQL injection (BUG-7) is a critical vulnerability; payload validation missing (BUG-8)
- **Production Ready:** NO
- **Recommendation:** Fix BUG-1, BUG-2, BUG-3, BUG-4, BUG-6, BUG-7, BUG-8 before deployment. BUG-3 alone makes the entire full sync branch non-functional. BUG-1 makes event routing fundamentally broken. BUG-7 is a security vulnerability that must be addressed.

### Bug Fix Round (2026-02-26)

All 12 bugs addressed:
- **FIXED (11):** BUG-1, BUG-2, BUG-3, BUG-4, BUG-5, BUG-6, BUG-7, BUG-8, BUG-10, BUG-11, BUG-12
- **PARTIALLY FIXED (1):** BUG-9 (error message truncation added; full hardening deferred to Phase 3)
- **Production Ready:** Ready for re-QA

---

### Re-QA Test Results (Round 2)

**Tested:** 2026-02-26
**Artifacts Reviewed:** `workflows/core/alice-ha-intent-sync.json`, `docs/ha-automations/*.yaml`, `schemas/ha-intent.json`
**Tester:** QA Engineer (AI)

#### Bug Fix Verification

| Bug | Original Severity | Fix Status | Verification |
| --- | --- | --- | --- |
| BUG-1: Event Router miswires | Critical | FIXED | PASS -- Switch node uses OR combinator for ha_start/templates_updated in a single rule. 3 rules + 1 fallback = 4 outputs. Connections map correctly: 0->Full Sync, 1->Incr Sync, 2->Remove, 3->Log Unknown. |
| BUG-2: Fallback output no connection | Critical | FIXED | PASS -- Output index 3 connects to "Log Unknown Event" node. |
| BUG-3: JS syntax error in Generate Utterances | Critical | FIXED | PASS -- Variable renamed to `hassilTemplates` (no space). Valid JavaScript identifier. |
| BUG-4: ha_sync_log stuck at running | High | FIXED | PASS -- try/catch in Fetch Exposed Entities returns `_ha_error: true`. HA Error Gate routes to error handler path that updates sync log to `status = 'error'`. |
| BUG-5: No-op check ignores area_name | Medium | FIXED | PASS -- `ex.area_name === entity.area_name` added to no-op comparison in "Incr Sync: Generate & Insert". |
| BUG-6: Incr conflict check ignores full syncs | Medium | FIXED | PASS -- Conflict check query: `WHERE status = 'running' AND started_at > NOW() - INTERVAL '5 minutes'` -- no sync_type filter. Blocks ALL concurrent syncs. |
| BUG-7: SQL injection via MQTT payload | Critical | FIXED | PASS -- All 6 affected nodes converted to Code-node SQL building with escaping. Single-quote doubling, numeric validation, whitelist for status values, regex sanitization for entity_id/domain. Entity_id validated at MQTT ingestion point with `^[a-z_]+\.[a-z0-9_]+$`. |
| BUG-8: No MQTT payload schema validation | High | FIXED | PASS -- Parse MQTT Message validates: JSON parse (try/catch), object check, event as non-empty string, entity_id for entity events with regex `^[a-z_]+\.[a-z0-9_]+$`. Invalid payloads routed to `__invalid__` -> fallback handler. |
| BUG-9: Error logs leak details | Low | PARTIAL FIX | PASS -- Error messages truncated (500 chars HA error, 1000 chars total, 200 chars per entry). Full API response bodies no longer stored. Acceptable for Phase 3 hardening. |
| BUG-10: Orphan nodes | Medium | FIXED | PASS -- All nodes in `nodes` array are connected in `connections` map. No orphans remain. |
| BUG-11: Misleading node name | Low | FIXED | PASS -- Node renamed to "Full Sync: Fetch Exposed Entities (REST)". |
| BUG-12: Hardcoded certaintyThreshold | Low | FIXED | PASS -- Both full sync and incremental sync read `process.env.CERTAINTY_THRESHOLD` with fallback to 0.82. |

**Bug Fix Verification: 11/11 FIXED verified, 1/1 PARTIAL FIX verified. All original bugs resolved.**

#### Acceptance Criteria Re-test

##### AC-1: MQTT Events (HA Automations) -- PASS
- [x] `alice_sync_on_start`: platform homeassistant, event start, 30s delay, correct topic/payload, QoS 1, retain false.
- [x] `alice_sync_on_entity_created`: event entity_registry_updated action create, 5s delay, mode queued max 10.
- [x] `alice_sync_on_entity_removed`: event entity_registry_updated action remove, no delay, mode queued max 10.

##### AC-2: n8n Workflow Event Routing -- PASS
- [x] Workflow triggered by MQTT topic `alice/ha/sync`.
- [x] All four event types handled correctly: ha_start -> Full Sync, templates_updated -> Full Sync (via OR combinator), entity_created -> Incr Sync, entity_removed -> Remove.
- [x] Unknown event types routed to "Log Unknown Event" via fallback output.

##### AC-3: Full Sync Logic -- PASS
- [x] Fetches entity registry via `GET /api/config/entity_registry/list` and area registry via `GET /api/config/area_registry/list`.
- [x] Diffs fetched entities against `alice.ha_entities` (added, updated, removed detection).
- [x] Utterances generated from matching templates using `{name}`, `{area}`, `{where}` placeholders.
- [x] Batch insert max 100 per batch (`BATCH_SIZE = 100`).
- [x] Uses `entityId` (camelCase) matching `schemas/ha-intent.json`.
- [x] Removed entities deleted from Weaviate via `where` filter on `entityId`.
- [x] `alice.ha_entities` updated via upsert with `ON CONFLICT (entity_id) DO UPDATE`.

##### AC-4: Logging and Timing -- PASS (with deployment verification needed)
- [x] `ha_sync_log` entry created at start with `status = 'running'`.
- [x] Updated at end with `status = 'success'`, `'partial'`, or `'error'` (whitelist validated).
- [x] `sync_type` reflects trigger: `'full'` for ha_start/templates_updated, `'incremental'` for entity_created/removed.
- [ ] **Deferred to deployment:** < 30 second timing and 60 second end-to-end latency require live testing.

##### Edge Cases Re-test -- PASS
- [x] EC-1: HA API unreachable -- try/catch returns `_ha_error: true`, HA Error Gate routes to error log update.
- [x] EC-2: Entity has no friendly_name -- fallback uses entity_id parts.
- [x] EC-3: Entity has no area -- only name-based utterances generated.
- [x] EC-4: No templates for domain -- skipped with console.log warning.
- [x] EC-5: Duplicate friendly_name -- utterances generated independently for each entity.
- [x] EC-6: No-op incremental -- compares friendly_name, area_id, area_name, aliases.
- [x] EC-7: Weaviate batch partially fails -- failed objects logged, status set to 'partial' or 'error'.
- [x] EC-8: Concurrent sync conflict -- conflict check blocks any running sync (no sync_type filter).
- [x] EC-9: templates_updated during full sync -- conflict guard prevents concurrent execution.

##### Security Re-test -- PASS (with notes)
- [x] SEC-1: SQL injection mitigated -- all queries use sanitized SQL via code nodes.
- [x] SEC-2: MQTT payload validated -- schema validation at ingestion point.
- [x] SEC-3: Weaviate auth -- acceptable risk (internal Docker network, VPN-only).
- [x] SEC-4: HA Token -- read from `process.env.HA_TOKEN`, not hardcoded.
- [x] SEC-5: Error message truncation added.

#### New Bugs Found in Re-QA

##### BUG-13: Incremental sync has no HA API error handling (same class as original BUG-4)
- **Severity:** High
- **Steps to Reproduce:**
  1. Make HA API unreachable (e.g., stop HA container)
  2. Publish `{"event": "entity_created", "entity_id": "light.test_lamp"}` to `alice/ha/sync`
  3. "Incr Sync: Fetch Entity from HA" code node calls HA API and receives an error
  4. The code uses `throw new Error(...)` (line: `if (!regResp.ok) throw new Error(...)`)
  5. Expected: `ha_sync_log` updated to `status = 'error'`, sync log accurately reflects the failure
  6. Actual: n8n execution fails with unhandled error. The `ha_sync_log` entry (created by "Incr Sync: Create Log (running)") remains `status = 'running'` until the 5-minute stale threshold
- **Root Cause:** BUG-4 fix was applied only to the full sync branch. The incremental sync branch ("Incr Sync: Fetch Entity from HA") still uses `throw new Error()` without try/catch and has no HA Error Gate equivalent.
- **Impact:** Stale `running` entries block subsequent syncs for up to 5 minutes. Sync log inaccurately reports status.
- **Priority:** Fix before deployment

##### BUG-14: Incremental sync no-op skip does not update ha_sync_log
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Entity `light.wohnzimmer` already exists in `alice.ha_entities` with identical data
  2. Publish `{"event": "entity_created", "entity_id": "light.wohnzimmer"}` to `alice/ha/sync`
  3. Incremental sync starts, creates log entry with `status = 'running'`
  4. "Incr Sync: Generate & Insert" detects no change and returns `{ skip_reason: 'no_change', status: 'success' }`
  5. The flow continues to "Incr Sync: PG Upsert Entity" which checks `if (!entity || !entity.entity_id)` -- since the no-op skip output has `entity` data intact, it still runs the upsert
  6. Expected: The sync log is updated to `status = 'success'` with indication that nothing changed
  7. Actual: The sync log IS updated (flow continues through PG Upsert -> Log Update), but the log shows `entities_added = 1` and `intents_generated = 0` which is misleading for a no-op
- **Root Cause:** The no-op skip case does not short-circuit the flow; it continues through the full incremental pipeline. The log completion node always sets `entities_added = 1`.
- **Priority:** Fix in next sprint

##### BUG-15: Full Sync conflict gate relies on `$json.length` which may be undefined for empty Postgres results
- **Severity:** Medium
- **Steps to Reproduce:**
  1. No running syncs exist in `ha_sync_log` (conflict check returns 0 rows)
  2. n8n Postgres node v2.5 may return 0 items (no output) or 1 item with empty JSON
  3. "Full Sync: Skip if Conflict" If node checks `{{ $json.length }} === 0`
  4. Expected: Condition evaluates to true (no conflict), full sync proceeds
  5. Actual: If Postgres returns 0 items, the If node receives no input items and may not execute either branch. If it returns `[{ json: {} }]`, then `$json.length` is `undefined`, not `0`, and the condition fails (routes to false/conflict branch, incorrectly skipping the sync)
- **Root Cause:** The conflict check assumes the Postgres node returns a specific structure for empty results. The same issue exists for "Incr Sync: Skip if Conflict".
- **Impact:** Could cause all syncs to be incorrectly skipped due to false conflict detection. Requires live n8n deployment testing to confirm.
- **Note:** This may work correctly depending on the specific n8n Postgres node v2.5 behavior for empty result sets. **Must be verified during deployment testing.**
- **Priority:** Verify during deployment (potentially Critical if confirmed)

#### Regression Testing

##### PROJ-1 (HA Intent Infrastructure)
- [x] No schema changes. `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` used as-is.
- [x] Weaviate `HAIntent` collection schema unchanged.

##### PROJ-2 (FastAPI hassil-parser)
- [x] `templates_updated` event correctly routed to Full Sync (BUG-1 fixed, verified).

##### PROJ-3 (HA-First Chat Handler)
- [x] No changes to `alice-chat-handler`. Reads from Weaviate `HAIntent` which PROJ-4 populates. No regression risk.

#### Re-QA Summary

- **Original Bug Fixes Verified:** 12/12 (11 FIXED confirmed, 1 PARTIAL confirmed)
- **Acceptance Criteria:** 14/15 passed, 0 failed, 1 deferred to deployment (timing)
- **New Bugs Found:** 3 (0 Critical, 1 High, 2 Medium)
  - BUG-13 (High): Incremental sync lacks HA API error handling
  - BUG-14 (Medium): No-op incremental sync misreports entities_added in log
  - BUG-15 (Medium): Conflict gate $json.length check may fail for empty Postgres results -- needs deployment verification
- **Security:** PASS -- all original security issues (BUG-7, BUG-8) verified fixed
- **Production Ready:** NO -- BUG-13 must be fixed first (same class as BUG-4 which was deemed fix-before-deployment). BUG-15 must be verified during deployment testing.
- **Recommendation:** Fix BUG-13 (add try/catch + error handler to incremental sync, same pattern as full sync BUG-4 fix). BUG-14 and BUG-15 can be fixed in next sprint or during deployment.

### Bug Fix Round 2 (2026-02-26)

All 3 re-QA bugs addressed:

#### BUG-13: Incremental sync has no HA API error handling -- FIXED
- **Severity:** High
- **Fix:** Wrapped HA API calls in `Incr Sync: Fetch Entity from HA` code node in try/catch (same pattern as BUG-4 fix for full sync). On error, returns `_ha_error: true` with error details. Added 3 new nodes:
  - `Incr Sync: HA Error Gate` (If node) -- routes `_ha_error === false` to No-op Gate, `_ha_error === true` to error handler
  - `Incr Sync: Log HA Error` (Code node) -- builds safe SQL to update sync log to `status = 'error'`
  - `Incr Sync: Execute HA Error Log Update` (Postgres node) -- executes the error log update
- Connections updated: `Fetch Entity from HA` -> `HA Error Gate` -> (true: `No-op Gate`, false: `Log HA Error` -> `Execute HA Error Log Update`)

#### BUG-14: Incremental sync no-op skip misreports entities_added -- FIXED
- **Severity:** Medium
- **Fix:** Updated `Incr Sync: Update Log (complete)` code node to detect `skip_reason === 'no_change'` from the Generate & Insert output. When detected, sets `entities_added = 0` (instead of hardcoded `1`) and adds `details` JSON with `skip_reason` and `entity_id` for debugging. Normal (non-no-op) flow is unchanged.

#### BUG-15: Conflict gate $json.length check may fail for empty Postgres results -- FIXED
- **Severity:** Medium
- **Fix:** Replaced `$json.length === 0` condition in both `Full Sync: Skip if Conflict` and `Incr Sync: Skip if Conflict` If nodes with `$json.id notExists` check. This works reliably regardless of how the n8n Postgres node v2.5 returns empty results: whether it outputs an empty JSON object `{}` (no `id` field) or no items at all (node receives no input, `$json.id` is undefined). The `notExists` operator handles both cases correctly, routing to the true/proceed branch. When a running sync IS found, `$json.id` exists (from the `SELECT id` query), routing to the false/conflict-skip branch. Also changed `typeValidation` from `strict` to `loose` to handle undefined values gracefully.

**Production Ready:** Ready for re-QA

---

### Re-QA Test Results (Round 3)

**Tested:** 2026-02-26
**Artifacts Reviewed:** `workflows/core/alice-ha-intent-sync.json`, `docs/ha-automations/*.yaml`, `schemas/ha-intent.json`
**Tester:** QA Engineer (AI)

#### Bug Fix Verification (Round 2 Fixes)

| Bug | Original Severity | Fix Status | Verification |
| --- | --- | --- | --- |
| BUG-13: Incr sync no HA API error handling | High | FIXED | PASS -- `Incr Sync: Fetch Entity from HA` wraps all HA API calls in try/catch. On error, returns `_ha_error: true`. New `Incr Sync: HA Error Gate` routes errors to `Incr Sync: Log HA Error` -> `Incr Sync: Execute HA Error Log Update` which updates sync log to `status = 'error'`. Connection chain verified: Fetch Entity -> HA Error Gate -> (output 0: No-op Gate, output 1: Log HA Error -> Execute HA Error Log Update). |
| BUG-14: No-op skip misreports entities_added | Medium | FIXED | PASS -- `Incr Sync: Update Log (complete)` detects `skip_reason === 'no_change'` and sets `entitiesAdded = isNoOp ? 0 : 1`. Also adds `details` JSON with `skip_reason` and `entity_id`. |
| BUG-15: Conflict gate $json.length check | Medium | FIXED | PASS -- Both `Full Sync: Skip if Conflict` and `Incr Sync: Skip if Conflict` use `$json.id notExists` operator with `typeValidation: "loose"`. This correctly handles: (a) empty Postgres result (no `id` field) -> proceeds with sync, (b) result with `id` field (running sync found) -> routes to conflict skip. |

**Bug Fix Verification: 3/3 FIXED verified.**

#### Acceptance Criteria Re-test

##### AC-1: MQTT Events (HA Automations) -- PASS
- [x] `alice_sync_on_start`: platform homeassistant event start, 30s delay, topic `alice/ha/sync`, payload includes `event: "ha_start"`, `sync_type: "full"`, QoS 1, retain false.
- [x] `alice_sync_on_entity_created`: event `entity_registry_updated` action create, 5s delay, mode queued max 10.
- [x] `alice_sync_on_entity_removed`: event `entity_registry_updated` action remove, no delay, mode queued max 10.

##### AC-2: n8n Workflow Event Routing -- PASS
- [x] Workflow triggered by MQTT topic `alice/ha/sync`.
- [x] All four event types handled: `ha_start` -> Full Sync (output 0), `templates_updated` -> Full Sync (output 0, via OR combinator), `entity_created` -> Incr Sync (output 1), `entity_removed` -> Remove (output 2).
- [x] Unknown event types routed to "Log Unknown Event" via fallback output (index 3).

##### AC-3: Full Sync Logic -- PASS
- [x] Fetches entity registry via `GET /api/config/entity_registry/list` and area registry via `GET /api/config/area_registry/list`.
- [x] Diffs fetched entities against `alice.ha_entities` (added, updated, removed detection via friendly_name, area_id, area_name, aliases comparison).
- [x] Utterances generated from matching templates using `{name}`, `{area}`, `{where}` placeholders. Patterns with `{value}`, `{message}`, `{temperature}` correctly skipped.
- [x] Batch insert max 100 per batch (`BATCH_SIZE = 100`).
- [x] Uses `entityId` (camelCase) matching `schemas/ha-intent.json`.
- [x] Removed entities deleted from Weaviate via `where` filter on `entityId`.
- [x] `alice.ha_entities` updated via upsert with `ON CONFLICT (entity_id) DO UPDATE`.

##### AC-4: Logging and Timing -- PASS (with deployment verification needed)
- [x] `ha_sync_log` entry created at start with `status = 'running'`.
- [x] Updated at end with `status = 'success'`, `'partial'`, or `'error'` (whitelist validated).
- [x] `sync_type` reflects trigger: `'full'` for ha_start/templates_updated, `'incremental'` for entity_created/removed.
- [ ] **Deferred to deployment:** < 30 second timing and 60 second end-to-end latency require live testing.

##### Edge Cases Re-test -- PASS
- [x] EC-1: HA API unreachable -- try/catch in both full sync and incremental sync (BUG-4 + BUG-13 fixes). Returns `_ha_error: true`, routed via HA Error Gate to error log update.
- [x] EC-2: Entity has no friendly_name -- fallback uses entity_id parts.
- [x] EC-3: Entity has no area -- only name-based utterances generated.
- [x] EC-4: No templates for domain -- skipped with console.log warning.
- [x] EC-5: Duplicate friendly_name -- utterances generated independently for each entity.
- [x] EC-6: No-op incremental -- compares friendly_name, area_id, area_name, aliases. No-op returns `skip_reason: 'no_change'`.
- [x] EC-7: Weaviate batch partially fails -- failed objects logged, status set to 'partial' or 'error'.
- [x] EC-8: Concurrent sync conflict -- both conflict checks use `WHERE status = 'running' AND started_at > NOW() - INTERVAL '5 minutes'` with no sync_type filter.
- [x] EC-9: templates_updated during full sync -- conflict guard prevents concurrent execution.

##### Security Re-test -- PASS (with notes)
- [x] SEC-1: SQL injection mitigated -- all Postgres nodes use code-node-built SQL with single-quote escaping, numeric validation, regex sanitization for entity_id/domain, whitelist for status values.
- [x] SEC-2: MQTT payload validated -- JSON parse with try/catch, event as non-empty string, entity_id regex `^[a-z_]+\.[a-z0-9_]+$`. Invalid payloads routed to `__invalid__` -> fallback handler.
- [x] SEC-3: Weaviate auth -- acceptable risk (internal Docker network, VPN-only).
- [x] SEC-4: HA Token -- read from `process.env.HA_TOKEN`, not hardcoded.
- [x] SEC-5: Error message truncation -- 500 chars HA error, 1000 chars total, 200 chars per batch error entry.

##### Workflow Integrity Check -- PASS
- [x] 45 nodes total, all with unique IDs and names.
- [x] All connection sources and targets reference valid node names.
- [x] No orphan nodes (all nodes connected in the graph).
- [x] No overlapping node positions.
- [x] Event Router has 4 outputs (3 rules + 1 fallback) correctly mapped to Full Sync, Incr Sync, Remove, Log Unknown.

#### New Bugs Found in Re-QA Round 3

##### BUG-16: Incremental sync no-op passes undefined query to Postgres Execute node
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Entity `light.wohnzimmer` already exists in `alice.ha_entities` with identical data
  2. Publish `{"event": "entity_created", "entity_id": "light.wohnzimmer"}` to `alice/ha/sync`
  3. Incremental sync detects no change in "Generate & Insert" code node
  4. Returns `{ log_id, skip_reason: 'no_change', entity_id, intents_generated: 0, status: 'success' }` -- note: no `entity` object
  5. "PG Upsert Entity" code node checks `if (!entity || !entity.entity_id)` -> true -> returns `{ json: data }` without a `query` field
  6. "Execute PG Upsert" Postgres node evaluates `={{ $json.query }}` -> resolves to the string `"undefined"`
  7. Expected: Flow continues cleanly to Update Log (complete) with no database error
  8. Actual: Postgres node attempts to run `"undefined"` as SQL -> syntax error -> n8n execution error, flow stops, sync log stuck at `status = 'running'`
- **Root Cause:** The no-op skip case in "PG Upsert Entity" passes through data without setting a `query` field. Should set `query` to a no-op SQL statement like `SELECT 1` for the skip case.
- **Impact:** Every no-op incremental sync (same entity, no changes) will error and leave the sync log at `running`, blocking subsequent syncs for 5 minutes.
- **Priority:** Fix before deployment

##### BUG-17: Incremental sync for not-exposed entity leaves ha_sync_log stuck at 'running'
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Add an entity to HA that has `conversation.should_expose = false`
  2. HA publishes `{"event": "entity_created", "entity_id": "sensor.not_exposed_thing"}` to `alice/ha/sync`
  3. Incremental sync starts: Conflict Check -> Create Log (running) -> Fetch Entity from HA
  4. Fetch Entity detects `should_expose === false` and returns `{ skip: true, _ha_error: false, ... }`
  5. HA Error Gate: `_ha_error === false` -> routes to No-op Gate (output 0)
  6. No-op Gate: `skip !== false` (skip is true) -> routes to output 1 -> "Log Skip"
  7. "Log Skip" only does `console.log` and returns `[]`
  8. Expected: `ha_sync_log` entry updated to `status = 'success'` with a note that entity was skipped
  9. Actual: `ha_sync_log` entry remains at `status = 'running'` indefinitely (until 5-minute stale threshold)
- **Root Cause:** The "Log Skip" node does not update the sync log. When used from "Skip if Conflict" (output 1), this is correct because no log entry exists yet. But when used from "No-op Gate" (output 1), a log entry was already created by "Create Log (running)" and needs to be closed.
- **Impact:** Each not-exposed entity event blocks subsequent incremental syncs for up to 5 minutes. In environments with many non-exposed entities, this could cause frequent sync blockage.
- **Priority:** Fix before deployment

##### BUG-18: Remove branch and Weaviate operations have no try/catch for network errors
- **Severity:** Low
- **Steps to Reproduce:**
  1. Make Weaviate completely unreachable (stop container)
  2. Trigger entity_removed: `{"event": "entity_removed", "entity_id": "light.test"}`
  3. "Remove: Delete from Weaviate" code node calls `fetch()` to Weaviate
  4. `fetch()` throws a network-level error (ECONNREFUSED)
  5. Expected: Error handled gracefully, entity still deactivated in PostgreSQL
  6. Actual: Unhandled error crashes the Remove branch. Entity remains active in PostgreSQL. No sync log entry records the failure.
  7. Same issue affects full sync Weaviate nodes ("Delete Weaviate (updated+removed)", "Batch Insert Weaviate") and incremental sync Generate & Insert Weaviate operations -- though those are partially protected by the sync log eventually timing out after 5 minutes.
- **Root Cause:** The Weaviate `fetch()` calls check `resp.ok` for HTTP errors but do not wrap `fetch()` in try/catch for network-level errors (connection refused, timeout, DNS failure).
- **Impact:** Low in practice since Weaviate runs on the same Docker network and is highly available. The full sync branch is more protected because it has an active sync log entry that will timeout. The remove branch has no sync log protection at all.
- **Priority:** Fix in next sprint

#### Regression Testing

##### PROJ-1 (HA Intent Infrastructure)
- [x] No schema changes. `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` used as-is.
- [x] Weaviate `HAIntent` collection schema unchanged. All properties match `schemas/ha-intent.json`.

##### PROJ-2 (FastAPI hassil-parser)
- [x] `templates_updated` event correctly routed to Full Sync via OR combinator in Switch node.

##### PROJ-3 (HA-First Chat Handler)
- [x] No changes to `alice-chat-handler`. Reads from Weaviate `HAIntent` which PROJ-4 populates. No regression risk.

#### Re-QA Round 3 Summary

- **Previous Bug Fixes Verified:** 3/3 (BUG-13, BUG-14, BUG-15 all confirmed fixed)
- **Acceptance Criteria:** 14/15 passed, 0 failed, 1 deferred to deployment (timing)
- **New Bugs Found:** 3 (0 Critical, 0 High, 2 Medium, 1 Low)
  - BUG-16 (Medium): No-op incremental sync passes undefined query to Postgres -> execution error, sync log stuck
  - BUG-17 (Medium): Not-exposed entity incremental sync leaves sync log stuck at 'running'
  - BUG-18 (Low): Weaviate network errors not caught in Remove branch and code nodes
- **Security:** PASS -- all previously identified security issues remain fixed
- **Production Ready:** NO -- BUG-16 and BUG-17 must be fixed first. Both can cause sync log entries to remain stuck at `status = 'running'`, which blocks subsequent syncs for up to 5 minutes. BUG-16 affects the common no-op case (entity already synced, no changes), making it likely to occur in production.
- **Recommendation:** Fix BUG-16 (set `query` to `'SELECT 1'` in PG Upsert Entity no-op case) and BUG-17 (add a dedicated "Log Skip with Sync Log Update" path from No-op Gate output 1 that updates the sync log to `status = 'success'`). BUG-18 can be addressed in next sprint.

### Bug Fix Round 3 (2026-02-26)

All 3 re-QA round 3 bugs addressed:

#### BUG-16: Incremental sync no-op passes undefined query to Postgres -- FIXED
- **Severity:** Medium
- **Fix:** In "Incr Sync: PG Upsert Entity" code node, the no-op skip case (`!entity || !entity.entity_id`) now returns `{ ...data, query: 'SELECT 1' }` instead of `{ json: data }` without a query field. The downstream "Execute PG Upsert" Postgres node safely executes `SELECT 1` as a no-op, and the flow continues cleanly to the log update node.

#### BUG-17: Not-exposed entity incremental sync leaves ha_sync_log stuck at 'running' -- FIXED
- **Severity:** Medium
- **Fix:** Updated "Incr Sync: Log Skip" code node to detect when a `log_id` exists in the input data (indicating a sync log entry was created by "Create Log (running)"). When `log_id` is present, the node builds a safe SQL UPDATE to set `status = 'success'`, `entities_added = 0`, `intents_generated = 0`, and includes `details` JSON with `skip_reason` and `entity_id`. Added new "Incr Sync: Execute Skip Log Update" Postgres node connected after "Log Skip" to execute the query. When no `log_id` exists (conflict skip path), the node returns `[]` as before. This ensures sync log entries are always properly closed.

#### BUG-18: Weaviate fetch calls lack try/catch for network errors -- FIXED
- **Severity:** Low
- **Fix:** Wrapped all Weaviate `fetch()` calls in try/catch blocks in 4 code nodes:
  - "Remove: Delete from Weaviate" -- catches network errors, returns `weaviate_error` field, continues to PG deactivation
  - "Full Sync: Delete Weaviate (updated+removed)" -- catches network errors per entity, adds to `errors` array
  - "Full Sync: Batch Insert Weaviate" -- catches network errors per batch, adds to `batchErrors` array
  - "Incr Sync: Generate & Insert" -- catches network errors for both DELETE and POST calls, tracks in `weaviate_errors` array, sets `status` to `'partial'` or `'error'` accordingly

**Production Ready:** Ready for re-QA

---

### Re-QA Test Results (Round 4)

**Tested:** 2026-02-26
**Artifacts Reviewed:** `workflows/core/alice-ha-intent-sync.json` (875 lines), `docs/ha-automations/*.yaml`, `schemas/ha-intent.json`
**Tester:** QA Engineer (AI)

#### Bug Fix Verification (Round 3 Fixes)

| Bug | Original Severity | Fix Status | Verification |
| --- | --- | --- | --- |
| BUG-16: No-op incremental passes undefined query to Postgres | Medium | FIXED | PASS -- `Incr Sync: PG Upsert Entity` code node now returns `{ ...data, query: 'SELECT 1' }` in the no-op skip case (`!entity || !entity.entity_id`). Downstream `Incr Sync: Execute PG Upsert` safely executes `SELECT 1`. Flow continues to `Update Log (complete)`. |
| BUG-17: Not-exposed entity leaves ha_sync_log stuck at running | Medium | FIXED | PASS -- `Incr Sync: Log Skip` code node detects `log_id` presence, builds safe SQL UPDATE to close the sync log entry with `status = 'success'`, `entities_added = 0`, `intents_generated = 0`, and `details` JSON with `skip_reason`. Connected to new `Incr Sync: Execute Skip Log Update` Postgres node. When no `log_id` exists (conflict skip path), returns `[]` so downstream node does not execute. |
| BUG-18: Weaviate fetch calls lack try/catch for network errors | Low | FIXED | PASS -- All 4 Weaviate code nodes verified with try/catch: (1) `Remove: Delete from Weaviate` catches network errors, returns `weaviate_error` field, continues to PG deactivation. (2) `Full Sync: Delete Weaviate (updated+removed)` catches per-entity errors, appends to `errors` array. (3) `Full Sync: Batch Insert Weaviate` catches per-batch errors, appends to `batchErrors` array. (4) `Incr Sync: Generate & Insert` has 2 try/catch blocks (DELETE and POST), tracks in `weaviate_errors` array. |

**Bug Fix Verification: 3/3 FIXED verified.**

#### Acceptance Criteria Re-test

##### AC-1: MQTT Events (HA Automations) -- PASS
- [x] `alice_sync_on_start`: platform homeassistant event start, 30s delay, topic `alice/ha/sync`, payload `{"event": "ha_start", "sync_type": "full", "timestamp": "..."}`, QoS 1, retain false, mode single.
- [x] `alice_sync_on_entity_created`: event `entity_registry_updated` action create, 5s delay, mode queued max 10, correct payload with `entity_id` from trigger data.
- [x] `alice_sync_on_entity_removed`: event `entity_registry_updated` action remove, no delay, mode queued max 10, correct payload.

##### AC-2: n8n Workflow Event Routing -- PASS
- [x] Workflow triggered by MQTT topic `alice/ha/sync` (MQTT Trigger node subscribes to `alice/ha/sync`).
- [x] Event Router: 3 rules + 1 fallback = 4 outputs. Rule 0 uses OR combinator for `ha_start` OR `templates_updated` -> output 0 -> Full Sync. Rule 1: `entity_created` -> output 1 -> Incr Sync. Rule 2: `entity_removed` -> output 2 -> Remove. Fallback output 3 -> Log Unknown Event.
- [x] Unknown event types routed to "Log Unknown Event" via fallback output. Invalid payloads (`__invalid__` event from Parse MQTT Message) also route to fallback.

##### AC-3: Full Sync Logic -- PASS
- [x] Fetches entity registry via `GET /api/config/entity_registry/list` and area registry via `GET /api/config/area_registry/list`.
- [x] Filters to entities exposed to assistant (checks `options.conversation.should_expose`).
- [x] Diffs fetched entities against `alice.ha_entities` -- identifies added, updated (by friendly_name, area_id, area_name, aliases comparison), removed.
- [x] Utterances generated from matching templates using `{name}`, `{area}`, `{where}` placeholders. Patterns with `{value}`, `{message}`, `{temperature}` correctly skipped. Aliases included as additional names.
- [x] Batch insert max 100 per batch (`BATCH_SIZE = 100`).
- [x] Uses `entityId` (camelCase) matching `schemas/ha-intent.json`.
- [x] Removed entities deleted from Weaviate via batch DELETE with `where` filter on `entityId`.
- [x] `alice.ha_entities` updated via upsert (`ON CONFLICT (entity_id) DO UPDATE`). Removed entities set to `is_active = false`.

##### AC-4: Logging and Timing -- PASS (with deployment verification needed)
- [x] `ha_sync_log` entry created at start with `status = 'running'` (both full and incremental branches).
- [x] Updated at end with `status = 'success'`, `'partial'`, or `'error'` (whitelist validated in code nodes).
- [x] `sync_type` reflects trigger: `'full'` for ha_start/templates_updated, `'incremental'` for entity_created/removed.
- [ ] **Deferred to deployment:** < 30 second timing and 60 second end-to-end latency require live testing.

#### Edge Cases Re-test -- ALL PASS

- [x] EC-1: HA API unreachable -- both full sync and incremental sync branches have try/catch with HA Error Gate routing to error log update. Sync log correctly set to `status = 'error'`.
- [x] EC-2: Entity has no friendly_name -- fallback: `entity_id.split('.').slice(1).join(' ').replace(/_/g, ' ')`.
- [x] EC-3: Entity has no area -- only name-based utterances generated (area variants skipped when `area` is null).
- [x] EC-4: No templates for domain -- skipped with `console.log` warning; returns empty utterances array.
- [x] EC-5: Duplicate friendly_name across areas -- utterances generated independently per entity.
- [x] EC-6: No-op incremental -- compares `friendly_name`, `area_id`, `area_name`, `aliases`. Returns `skip_reason: 'no_change'`. PG Upsert Entity returns `SELECT 1` (BUG-16 fix). Log updated with `entities_added = 0` (BUG-14 fix).
- [x] EC-7: Weaviate batch partially fails -- failed objects logged via `batchErrors` array, status set to `'partial'` (some succeed) or `'error'` (all fail).
- [x] EC-8: Concurrent sync conflict -- both full and incremental conflict checks query `WHERE status = 'running' AND started_at > NOW() - INTERVAL '5 minutes'` with no sync_type filter. Uses `$json.id notExists` operator with `typeValidation: "loose"` (BUG-15 fix).
- [x] EC-9: templates_updated during full sync -- conflict guard prevents concurrent execution.

#### Security Re-test -- PASS (with notes)

- [x] SEC-1: SQL injection mitigated -- all 6 originally affected Postgres nodes use code-node-built SQL with sanitization. Single-quote doubling via `replace(/'/g, "''")`, numeric validation via `Number()`, whitelist for status values, regex sanitization for entity_id (`/[^a-z0-9_.]/g`) and domain (`/[^a-z0-9_]/g`). Entity_id validated at MQTT ingestion with `^[a-z_]+\.[a-z0-9_]+$`.
- [x] SEC-2: MQTT payload validated -- Parse MQTT Message validates JSON parse (try/catch), object check, event as non-empty string, entity_id for entity events with regex. Invalid payloads get `event: '__invalid__'` routed to fallback handler.
- [x] SEC-3: Weaviate auth -- internal Docker network, no auth, VPN-only. Consistent with PROJ-1/3.
- [x] SEC-4: HA Token -- read from `process.env.HA_TOKEN`, not hardcoded.
- [x] SEC-5: Error message truncation -- 500 chars for HA errors, 1000 chars total for error_message, 200 chars per batch error entry. Full API response bodies not stored.
- [x] SEC-6: No hardcoded credentials in workflow JSON -- MQTT and Postgres credentials referenced by ID/name only.

#### Workflow Integrity Check -- PASS

- [x] 46 nodes total, all with unique IDs and unique names.
- [x] All connection sources and targets reference valid node names (programmatically verified).
- [x] No orphan nodes -- all 46 nodes appear in at least one connection as source or target.
- [x] No overlapping node positions.
- [x] Event Router has 4 outputs (3 rules + 1 fallback) correctly mapped to Full Sync, Incr Sync, Remove, Log Unknown.
- [x] Parallel merge nodes (Full Sync: Generate Utterances, Incr Sync: Generate & Insert) each have exactly 2 input connections, ensuring n8n waits for both before executing.

#### Notes for Deployment

- The entity_id regex `^[a-z_]+\.[a-z0-9_]+$` rejects entity IDs containing hyphens (e.g., `sensor.my-device_temp`). While rare in HA, some MQTT-based integrations may produce hyphenated entity IDs. This would cause those entities to be rejected at MQTT ingestion. Severity is Low since most HA entities use underscores, and if needed the regex can be expanded to `^[a-z_]+\.[a-z0-9_-]+$`.
- The `LIKE '${domain}_%'` clause in Incr Sync: Load Templates uses underscore as a LIKE wildcard. Since HA domains (light, switch, cover, etc.) never contain underscores, this is not an issue in practice.
- Timing AC (< 30s full sync, < 60s end-to-end) must be verified with live deployment.

#### Regression Testing

##### PROJ-1 (HA Intent Infrastructure)
- [x] No schema changes. `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` used as-is.
- [x] Weaviate `HAIntent` collection schema unchanged. All 8 properties match `schemas/ha-intent.json`.

##### PROJ-2 (FastAPI hassil-parser)
- [x] `templates_updated` event correctly routed to Full Sync via OR combinator in Switch node rule 0.

##### PROJ-3 (HA-First Chat Handler)
- [x] No changes to `alice-chat-handler`. Reads from Weaviate `HAIntent` which PROJ-4 populates. No regression risk.

#### Re-QA Round 4 Summary

- **Previous Bug Fixes Verified:** 3/3 (BUG-16, BUG-17, BUG-18 all confirmed fixed)
- **Cumulative Bug Status:** 15/15 bugs addressed (14 FIXED, 1 PARTIALLY FIXED -- BUG-9 deferred to Phase 3)
- **Acceptance Criteria:** 14/15 passed, 0 failed, 1 deferred to deployment (timing)
- **Edge Cases:** 9/9 passed
- **New Bugs Found:** 0
- **Security:** PASS -- all previously identified security issues remain fixed, no new vulnerabilities found
- **Production Ready:** YES
- **Recommendation:** Deploy to production. Verify timing AC (< 30s full sync, < 60s end-to-end) during deployment testing. Consider expanding entity_id regex to allow hyphens if needed post-deployment.

---

## Deployment

**Deployed:** 2026-02-26

### n8n Workflow
- **Workflow:** `alice-ha-intent-sync`
- **Workflow ID:** `YT4uorzjuMoCIthq`
- **Instance:** https://n8n.happy-mining.de
- **Status:** Active
- **Nodes:** 46
- **Trigger:** MQTT `alice/ha/sync`

### Home Assistant Automations
Install via HA UI (Settings → Automations → Import) or copy YAML to `config/automations/`:
- `docs/ha-automations/alice_sync_on_start.yaml` — full sync 30s after HA restart
- `docs/ha-automations/alice_sync_on_entity_created.yaml` — incremental sync on entity add
- `docs/ha-automations/alice_sync_on_entity_removed.yaml` — removal sync on entity delete

### Post-Deploy Timing Verification (deferred AC)
After installing HA automations, restart HA and verify:
- [ ] Full sync completes in < 30 seconds (check `alice.ha_sync_log`)
- [ ] New entity becomes matchable in PROJ-3 within 60 seconds
