# PROJ-4: HA Auto-Sync (MQTT → n8n → Weaviate)

## Status: Planned
**Created:** 2026-02-23
**Last Updated:** 2026-02-23

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — `alice.ha_entities`, `alice.ha_sync_log`, `alice.ha_intent_templates` must exist
- Requires: PROJ-2 (FastAPI Intent Helper) — templates with `{name}`/`{area}` placeholders must be populated
- Requires: PROJ-3 (HA-First Chat Handler) — Weaviate `HAIntent` collection must be in use

## Overview

Keeps the Weaviate `HAIntent` collection automatically in sync with Home Assistant. When HA starts, a new entity is added, or an entity is removed, an MQTT message triggers an n8n workflow that fetches the current entity registry, diffs it against `alice.ha_entities`, generates utterances using the stored templates, and updates Weaviate accordingly. New HA devices automatically become speakable within 60 seconds.

## User Stories

- As Andreas, I want a new smart home device to be controllable via Alice immediately after adding it to HA so that I never have to manually update intent lists.
- As Andreas, I want removed or renamed entities to stop matching in Alice so that I don't get errors for devices that no longer exist.
- As a developer, I want a full sync to run when HA restarts so that the system recovers automatically after HA updates.
- As a developer, I want every sync run logged in `alice.ha_sync_log` so that I can see what changed and debug failures.
- As a developer, I want to be able to trigger a manual full sync via MQTT so that I can force a refresh during development.

## Acceptance Criteria

- [ ] Home Assistant automation `alice_sync_on_start` publishes `{"event": "ha_start", "sync_type": "full"}` to `alice/ha/sync` 30 seconds after HA start
- [ ] Home Assistant automation `alice_sync_on_entity_created` publishes `{"event": "entity_created", "entity_id": "..."}` to `alice/ha/sync` 5 seconds after entity registry update with action `create`
- [ ] Home Assistant automation `alice_sync_on_entity_removed` publishes `{"event": "entity_removed", "entity_id": "..."}` to `alice/ha/sync` immediately after entity registry update with action `remove`
- [ ] n8n workflow `alice-ha-intent-sync` is triggered by MQTT topic `alice/ha/sync`
- [ ] Workflow fetches all states from `GET /api/states` and area registry from `GET /api/config/area_registry/list`
- [ ] Workflow diffs fetched entities against `alice.ha_entities` to find: added, removed, updated (friendly_name or area change)
- [ ] For each **added/updated** entity: generate utterances from matching templates in `alice.ha_intent_templates` using `{name}` → `friendly_name` + `aliases`, `{area}` → `area_name`, `{where}` → both area and name variants
- [ ] Generated utterances are batch-inserted into Weaviate `HAIntent` collection
- [ ] For each **removed** entity: all Weaviate objects with `sourceEntity = entity_id` are deleted
- [ ] `alice.ha_entities` table is updated to reflect current state after each sync
- [ ] `alice.ha_sync_log` entry created at start (status `running`) and updated at end (status `success` or `error`)
- [ ] Sync completes in < 30 seconds for a full sync of up to 200 entities
- [ ] New entity becomes matchable in PROJ-3 intent detection within 60 seconds of being added to HA

## Edge Cases

- HA API unreachable during sync: log error in `ha_sync_log`, set status to `error`, do not corrupt existing Weaviate data.
- Entity has no `friendly_name`: use `entity_id` parts (e.g. `light.wohnzimmer_decke` → "wohnzimmer decke") as fallback name.
- Entity has no area assigned: only generate name-based utterances (no area variants).
- Template `patterns` array is empty for a domain (e.g. templates not yet loaded): skip intent generation for that entity, log warning.
- Two entities have the same `friendly_name` in different areas: generate utterances for both; disambiguation handled by Weaviate certainty scores.
- MQTT message arrives for already-synced entity with no changes: detect via hash/timestamp comparison and skip Weaviate update (no-op).
- Weaviate batch insert partially fails (some objects rejected): log failed objects, continue with the rest, mark sync as `partial` in `ha_sync_log`.
- `incremental` sync triggered for a `create` event while a `full` sync is already running: queue the incremental, run after full sync completes.

## Technical Requirements

- HA automations written in YAML, committed to `docker/` or `docs/` as reference
- n8n workflow exported as JSON to `workflows/alice-ha-intent-sync.json`
- Batch size for Weaviate inserts: max 100 objects per batch
- Supported domains for intent generation: `light`, `switch`, `cover`, `media_player`, `climate`, `scene`, `lock`, `alarm_control_panel`

---

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
