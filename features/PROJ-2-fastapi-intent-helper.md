# PROJ-2: FastAPI Container + Python Helper (hassil Intent Expansion)

## Status: Planned
**Created:** 2026-02-23
**Last Updated:** 2026-02-23

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — `alice.ha_intent_templates` table must exist

## Overview

A Python FastAPI container that downloads the official Home Assistant intent sentences from GitHub, expands the Hassil template syntax into concrete utterances, and writes them into `alice.ha_intent_templates` (PostgreSQL). This replaces the need for manually maintained intent templates: after this runs, PROJ-3 can immediately use correct, comprehensive German HA utterances.

The container is also the general-purpose Python helper sidecar for n8n — used via shared volume (`/srv/warm/n8n/inbox`) for large data exchanges.

## User Stories

- As a developer, I want a FastAPI container on the `automation` network so that n8n can call Python processing tasks via HTTP.
- As a developer, I want a `POST /intents/sync` endpoint so that n8n can trigger a full import of official HA intent sentences.
- As a developer, I want the hassil syntax (`<rule>`, `[optional]`, `(alt1|alt2)`, `{slot}`) expanded into concrete patterns so that Weaviate can vectorize real German utterances.
- As a developer, I want the expanded patterns written into `alice.ha_intent_templates` (upsert, `source='github'`) so that the intent generator can use them without manual maintenance.
- As a developer, I want a shared volume at `/srv/warm/n8n/inbox` mounted in both n8n and the FastAPI container so that large data can be exchanged without HTTP payload limits.
- As a developer, I want a `GET /health` endpoint so that monitoring can verify the service is alive.

## Acceptance Criteria

- [ ] Docker Compose file at `docker/compose/automation/fastapi-processor.yml` (or added to existing automation compose)
- [ ] Container mounts `/srv/warm/n8n/inbox` as `/data_inbox` (same path as n8n)
- [ ] Container is on the `automation` Docker network (same as n8n)
- [ ] `GET /health` returns `{"status": "healthy"}` and HTTP 200
- [ ] `POST /intents/sync` downloads `https://github.com/home-assistant/intents/archive/main.zip`, expands all German sentences from `sentences/de/`, and upserts into `alice.ha_intent_templates`
- [ ] Hassil expansion handles: `<rule>` references, `[optional]` parts (with/without), `(alt1|alt2)` alternatives
- [ ] Each expanded pattern retains `{name}` and `{area}` slot placeholders (not filled with real entity names)
- [ ] Maximum 50 patterns per intent to prevent combinatorial explosion
- [ ] `source` field in `alice.ha_intent_templates` is set to `'github'` for all synced templates
- [ ] After sync, `POST /intents/trigger-entity-sync` publishes `{"event": "templates_updated", "source": "github"}` to MQTT topic `alice/ha/sync`
- [ ] Python script `scripts/expand_ha_intents.py` is committed to the repository and also available inside the container at `/scripts/expand_ha_intents.py`
- [ ] `requirements.txt` includes: `fastapi`, `uvicorn[standard]`, `pydantic`, `pyyaml`, `httpx`, `psycopg2-binary`
- [ ] Optional: `hassil` library used if available, custom expansion as fallback

## Edge Cases

- GitHub ZIP download fails (rate limit, network issue): return HTTP 503 with error detail; do not corrupt existing templates.
- Hassil expansion produces 0 patterns for an intent: skip that intent, log a warning.
- `{slot}` placeholders other than `{name}` and `{area}` (e.g. `{brightness}`, `{temperature}`): keep as-is in the pattern string for future parameter extraction.
- `excludes_context.domain` in HA intent files (e.g. `HassTurnOn` excludes `binary_sensor`, `lock`): store excluded domains in `default_parameters` JSONB so future logic can filter.
- Container restart while sync is running: sync is idempotent (upsert), so a re-run is safe.
- Shared volume not mounted (misconfiguration): `GET /health` returns `{"status": "degraded", "inbox_accessible": false}`.

## Technical Requirements

- Base image: `python:3.11-slim`
- Port: `8001` (internal, not exposed to host — only accessible via Docker network)
- PostgreSQL connection via env var `POSTGRES_CONNECTION` (same as n8n)
- MQTT connection via env var `MQTT_URL`
- Max patterns per intent: configurable via env var `MAX_PATTERNS_PER_INTENT` (default: 50)

---

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
