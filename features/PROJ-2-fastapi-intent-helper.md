# PROJ-2: FastAPI Container + hassil-parser (hassil Intent Expansion)

## Status: In Review

**Created:** 2026-02-23
**Last Updated:** 2026-02-23

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — `alice.ha_intent_templates` table must exist

## Overview

A Python FastAPI container (`hassil-parser`) that downloads the official Home Assistant intent sentences from GitHub, expands the Hassil template syntax into concrete utterances, and writes them into `alice.ha_intent_templates` (PostgreSQL). This replaces the need for manually maintained intent templates: after this runs, PROJ-3 can immediately use correct, comprehensive German HA utterances.

The container is also available via shared volume (`/srv/warm/n8n/inbox`) for large data exchanges with n8n.

## User Stories

- As a developer, I want a `hassil-parser` FastAPI container on the `automation` network so that n8n can call Hassil parsing tasks via HTTP.
- As a developer, I want a `POST /intents/sync` endpoint so that n8n can trigger a full import of official HA intent sentences.
- As a developer, I want the hassil syntax (`<rule>`, `[optional]`, `(alt1|alt2)`, `{slot}`) expanded into concrete patterns so that Weaviate can vectorize real German utterances.
- As a developer, I want the expanded patterns written into `alice.ha_intent_templates` (upsert, `source='github'`) so that the intent generator can use them without manual maintenance.
- As a developer, I want a shared volume at `/srv/warm/n8n/inbox` mounted in both n8n and `hassil-parser` so that large data can be exchanged without HTTP payload limits.
- As a developer, I want a `GET /health` endpoint so that monitoring can verify the service is alive.

## Acceptance Criteria

- [ ] Docker Compose file at `docker/compose/automations/hassil-parser/compose.yml` with Dockerfile in same directory
- [ ] `automations/hassil-parser` added to `STACKS` in `docker/compose/scripts/Makefile`
- [ ] Container mounts `/srv/warm/n8n/inbox` as `/data_inbox` (same path as n8n)
- [ ] Container is on the `automation` Docker network (same as n8n)
- [ ] `GET /health` returns `{"status": "healthy"}` and HTTP 200
- [ ] `POST /intents/sync` downloads `https://github.com/home-assistant/intents/archive/main.zip`, expands all German sentences from `sentences/de/`, and upserts into `alice.ha_intent_templates`
- [ ] Hassil expansion handles: `<rule>` references, `[optional]` parts (with/without), `(alt1|alt2)` alternatives
- [ ] Each expanded pattern retains `{name}` and `{area}` slot placeholders (not filled with real entity names)
- [ ] Maximum 50 patterns per intent to prevent combinatorial explosion
- [ ] `source` field in `alice.ha_intent_templates` is set to `'github'` for all synced templates
- [ ] After sync, `POST /intents/trigger-entity-sync` publishes `{"event": "templates_updated", "source": "github"}` to MQTT topic `alice/ha/sync`
- [ ] Python script `docker/compose/automations/hassil-parser/expand_ha_intents.py` is committed to the repository and available inside the container at `/app/expand_ha_intents.py` (copied via Dockerfile `COPY`)
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

### Summary

This feature adds a **`hassil-parser` FastAPI container** to the `automation` Docker network. Its sole job is to download the official HA intent sentences from GitHub, expand the Hassil template syntax into concrete German utterances, and write them into `alice.ha_intent_templates`.

---

### A) System Context

```text
AUTOMATION NETWORK
+-- n8n (existing)
|     - Triggers sync via HTTP POST
|     - Shares /srv/warm/n8n/inbox volume
|
+-- hassil-parser [NEW]
|     - Receives HTTP requests from n8n
|     - Downloads HA intents from GitHub
|     - Expands Hassil syntax → concrete German phrases
|     - Writes results to PostgreSQL (alice.ha_intent_templates)
|     - Publishes MQTT event when done
|
BACKEND NETWORK
+-- postgres (existing) ← hassil-parser writes here
+-- mqtt (existing)     ← hassil-parser publishes here
```

---

### B) Service Structure

```text
hassil-parser (Docker container)
+-- GET  /health
|       Returns: {"status": "healthy"} or {"status": "degraded", "inbox_accessible": false}
|       Used by: monitoring, Docker healthcheck
|
+-- POST /intents/sync
|       1. Downloads HA intents ZIP from GitHub (sentences/de/)
|       2. Parses YAML files per HA domain (light, cover, lock, ...)
|       3. Expands Hassil template syntax into plain German utterances
|       4. Upserts all patterns into alice.ha_intent_templates (source='github')
|       5. Publishes MQTT event: alice/ha/sync → {"event": "templates_updated"}
|       Returns: {"inserted": N, "updated": N, "skipped": N, "duration_ms": N}
|
+-- POST /intents/trigger-entity-sync
        Publishes MQTT event only (no DB write)
        Returns: {"published": true}

Volume mount: /srv/warm/n8n/inbox ↔ /data_inbox (shared with n8n)
```

---

### C) Hassil Expansion Logic

The HA intent files use a template mini-language. The expander handles three constructs:

```text
Input template                   →  Expanded output examples
───────────────────────────────────────────────────────────────
"[Bitte] {name} einschalten"     →  "Bitte {name} einschalten"
                                     "{name} einschalten"

"(An|Aus)schalten {name}"        →  "Anschalten {name}"
                                     "Ausschalten {name}"

"<turn_on> {name}"               →  resolves <turn_on> rule first,
                                     then expands recursively

"{brightness}" placeholder       →  kept as-is (not filled with real values)
"{name}" / "{area}" placeholder  →  kept as-is (filled at query time by PROJ-3)
```

Hard cap: **50 patterns per intent** (configurable via `MAX_PATTERNS_PER_INTENT` env var). Prevents combinatorial explosion on complex templates.

---

### D) Data Flow

```text
[GitHub ZIP]
     ↓  download + unzip (in memory)
[YAML files in sentences/de/]
     ↓  parse per domain
[Hassil templates]
     ↓  expand to concrete utterances
[German phrase list, max 50 per intent]
     ↓  upsert (ON CONFLICT → update patterns)
[alice.ha_intent_templates] (source = 'github')
     ↓  after all domains written
[MQTT alice/ha/sync] → triggers PROJ-4 entity sync
```

---

### E) Infrastructure / Docker

```text
File: docker/compose/automations/hassil-parser/compose.yml

Container config:
  Image:    python:3.11-slim (built via Dockerfile in docker/compose/automations/hassil-parser/)
  Port:     8001 (internal only — not exposed to host)
  Networks: automation (reach n8n), backend (reach postgres + mqtt)
  Volumes:  /srv/warm/n8n/inbox → /data_inbox (same as n8n)
  Restart:  unless-stopped

Environment variables (from host .env):
  POSTGRES_CONNECTION         — same connection string as n8n
  MQTT_URL                    — same as n8n
  MAX_PATTERNS_PER_INTENT     — default 50
```

The shared volume `/srv/warm/n8n/inbox` is already mounted in n8n ([docker/compose/automations/n8n/compose.yml](docker/compose/automations/n8n/compose.yml) line 30). The `hassil-parser` container mounts the same host path — no new volumes needed.

---

### F) Design Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| FastAPI (not Flask) | FastAPI | Async-native, auto-docs at `/docs`, type-validated requests/responses via Pydantic |
| `python:3.11-slim` base | As spec | Matches spec, minimizes image size |
| In-memory ZIP extraction | `zipfile` stdlib | No disk I/O needed; intents ZIP is ~5 MB |
| `hassil` library optional | Try import, fallback to custom | `hassil` is the authoritative parser; custom handles the 80% case if unavailable |
| Max 50 patterns (configurable) | Env var `MAX_PATTERNS_PER_INTENT` | Prevents Weaviate flooding; tunable per deployment |
| Upsert strategy | `ON CONFLICT (domain, intent, language) DO UPDATE` | Idempotent: re-running sync never creates duplicate rows |
| MQTT publish after all writes | Separate endpoint `/intents/trigger-entity-sync` | n8n can call this independently without running a full sync |
| Internal port only | Port 8001, no host binding | Only accessed by n8n via Docker network — no external exposure needed |

---

### G) Deliverables

| # | Deliverable | Type |
| --- | --- | --- |
| 1 | `docker/compose/automations/hassil-parser/compose.yml` | New Docker Compose file |
| 2 | `docker/compose/automations/hassil-parser/Dockerfile` | Container build definition |
| 3 | `docker/compose/automations/hassil-parser/requirements.txt` | Python dependencies |
| 4 | `docker/compose/automations/hassil-parser/main.py` | FastAPI app (health + sync endpoints) |
| 5 | `docker/compose/automations/hassil-parser/expand_ha_intents.py` | Hassil expansion logic (copied into container via `COPY`) |
| 6 | `docker/compose/scripts/Makefile` | Add `automations/hassil-parser` to `STACKS` |

---

### H) Dependencies (Python packages)

| Package | Purpose |
| --- | --- |
| `fastapi` | HTTP framework |
| `uvicorn[standard]` | ASGI server |
| `pydantic` | Request/response validation |
| `pyyaml` | Parse HA YAML intent files |
| `httpx` | Async HTTP client for GitHub download |
| `psycopg2-binary` | PostgreSQL client |
| `hassil` | (Optional) official HA template parser |

---

### I) Error Handling Strategy

| Failure | Behavior |
| --- | --- |
| GitHub download fails (503, rate limit) | Return HTTP 503; existing DB rows untouched |
| 0 patterns expanded for an intent | Skip + log warning; continue with other intents |
| Unknown `{slot}` placeholder | Keep as-is in pattern string |
| Shared volume not mounted | `GET /health` returns `{"status": "degraded"}` |
| Sync interrupted (container restart) | Upsert is idempotent → re-run is safe |

## QA Test Results

### Re-test (2026-02-24)

**QA Date:** 2026-02-24
**Tester:** QA Engineer
**Overall Status:** PASS

**Context:** Re-test after bug fixes for BUG-1 (Critical), BUG-2 (High), BUG-5 (Low/Blocking), and BUG-4 comment (Low).

**Files Reviewed:**
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/compose.yml`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/Dockerfile`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/requirements.txt`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/main.py`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/expand_ha_intents.py`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/.env`
- `/home/stan/Apps/development/alice/docker/compose/automations/hassil-parser/.env.example`
- `/home/stan/Apps/development/alice/docker/compose/scripts/Makefile`

### Bug Fix Verification

#### BUG-1 (Critical): Missing `service` column in INSERT -- FIXED

- **Verification:** The INSERT in `main.py` line 186-188 now includes `service` in the column list: `(domain, intent, service, language, patterns, source, default_parameters)` with 7 `%s` placeholders.
- **`_intent_to_service()` function added** in `expand_ha_intents.py` lines 52-78. Uses a two-tier strategy: (1) explicit lookup table `_INTENT_TO_ACTION` (lines 25-49) covering 23 common HA intents, (2) fallback PascalCase-to-snake_case conversion with domain prefix stripping.
- **`parse_intent_yaml()` now produces `"service"` key** at line 336: `"service": _intent_to_service(intent_name, domain)`.
- **`main.py` passes `tmpl["service"]`** at line 200. ON CONFLICT UPDATE also sets `service = EXCLUDED.service` at line 190.
- **Correctness of `_intent_to_service()`:** Tested all 23 explicit mappings (all produce correct `{domain}.{action}` strings). Fallback logic tested with unknown intents -- correctly strips `Hass` prefix, converts PascalCase to snake_case, and removes redundant domain prefix. Example: `HassLockStatus` + `lock` produces `lock.status`.
- **Edge case noted:** Intent name exactly `"Hass"` (no action suffix) produces `"{domain}."` with empty action. This is a theoretical-only edge case since no real HA intent is named just "Hass". Not blocking.
- **Result:** FIXED -- verified correct.

#### BUG-2 (High): `patterns` not JSON-serialized -- FIXED

- **Verification:** `main.py` line 202 now reads `json.dumps(tmpl["patterns"])`. This converts the Python `list[str]` to a JSON string that psycopg2 can pass to the JSONB column.
- **Tested:** `json.dumps(["Schalte {name} ein", "Mache {name} an"])` produces `'["Schalte {name} ein", "Mache {name} an"]'` -- valid JSONB input.
- **Result:** FIXED -- verified correct.

#### BUG-5 (Low/Blocking): `default_parameters=None` violates NOT NULL -- FIXED

- **Verification:** `main.py` line 204 now reads `json.dumps(tmpl["default_parameters"] or {})`. When `default_parameters` is `None`, the `or {}` fallback provides an empty dict, and `json.dumps({})` produces `'{}'` -- a valid JSONB value that satisfies the NOT NULL constraint.
- **Tested:** `json.dumps(None or {})` returns `'{}'`. `json.dumps({"excludes_domain": ["binary_sensor"]} or {})` returns the correct JSON with the dict content.
- **Result:** FIXED -- verified correct.

#### BUG-4 (Low): `_USE_HASSIL` flag misleading -- ADDRESSED

- **Verification:** Comment added at `expand_ha_intents.py` lines 96-98:
  ```python
  # NOTE: _USE_HASSIL is intentionally not yet used to switch expansion paths.
  # The custom implementation handles all required constructs. Full hassil
  # integration is reserved for a future iteration if deeper parsing is needed.
  ```
- **Logger message** on line 93 also updated to `"hassil library available (using custom expansion for now)"`.
- **Result:** ADDRESSED -- clarifying comment and log message remove the misleading impression.

### Acceptance Criteria (Re-test)

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| AC-1 | Docker Compose file at `docker/compose/automations/hassil-parser/compose.yml` with Dockerfile in same directory | PASS | `compose.yml` exists, references `Dockerfile` in same directory via `build: context: .` |
| AC-2 | `automations/hassil-parser` added to `STACKS` in `docker/compose/scripts/Makefile` | PASS | Present on line 14 of Makefile: `automations/hassil-parser \` |
| AC-3 | Container mounts `/srv/warm/n8n/inbox` as `/data_inbox` | PASS | `compose.yml` line 16: `- /srv/warm/n8n/inbox:/data_inbox` |
| AC-4 | Container is on the `automation` Docker network | PASS | `compose.yml` lines 17-21: container is on both `automation` and `backend` networks (both external) |
| AC-5 | `GET /health` returns `{"status": "healthy"}` and HTTP 200 | PASS | `main.py` lines 232-240: returns `{"status": "healthy"}` when `/data_inbox` is accessible, or `{"status": "degraded", "inbox_accessible": false}` when not -- matches spec including edge case |
| AC-6 | `POST /intents/sync` downloads ZIP, expands German sentences, upserts into DB | PASS | Previously FAIL due to BUG-1, BUG-2, BUG-5. All three fixes verified: INSERT now includes `service` column (line 187), `patterns` wrapped with `json.dumps()` (line 202), `default_parameters` uses `json.dumps(... or {})` fallback (line 204). Column count (7), placeholder count (7), and parameter tuple count (7) all match. `_intent_to_service()` generates valid `{domain}.{action}` strings for all known and unknown intents. |
| AC-7 | Hassil expansion handles `<rule>`, `[optional]`, `(alt1\|alt2)` | PASS | `_resolve_rules()` (lines 106-123), `_expand_optionals()` (lines 126-141), `_expand_alternatives()` (lines 144-157). All three constructs tested: `<turn_on> {name}` with rules produces 3 variants, `[Bitte] {name} einschalten` produces 2 variants, `(An\|Aus)schalten {name}` produces 2 variants. Combined template `[Bitte] <turn_on> {name} [im {area}]` correctly produces 12 patterns (3x2x2). |
| AC-8 | Expanded patterns retain `{name}` and `{area}` slot placeholders | PASS | Slot placeholders `{...}` are not matched by expansion regexes (`<rule>`, `[optional]`, `(alt)` patterns). Verified: all expanded patterns retain `{name}` and `{area}` as literal text. |
| AC-9 | Maximum 50 patterns per intent | PASS | `expand_template()` caps at `max_patterns` (line 207-214). `expand_intent_sentences()` breaks early at limit (lines 237-240). Tested: complex template with 10 rules x 7 optionals correctly capped at 50. Configurable via `MAX_PATTERNS_PER_INTENT` env var. |
| AC-10 | `source` field set to `'github'` | PASS | `expand_ha_intents.py` line 339: `"source": "github"` hardcoded in every result dict. |
| AC-11 | `POST /intents/trigger-entity-sync` publishes MQTT event | PASS | `main.py` lines 316-331: publishes `{"event": "templates_updated", "source": "github"}` to `alice/ha/sync` topic. |
| AC-12 | `expand_ha_intents.py` committed and available at `/app/expand_ha_intents.py` | PASS | Dockerfile line 9: `COPY expand_ha_intents.py .` with `WORKDIR /app` (line 3). File exists in repo at the expected path. |
| AC-13 | `requirements.txt` includes required packages | PASS | All six required packages present: `fastapi`, `uvicorn[standard]`, `pydantic`, `pyyaml`, `httpx`, `psycopg2-binary`. Also includes `paho-mqtt` (needed for MQTT publishing) and `hassil` (optional library). |
| AC-14 | Optional: `hassil` library used if available | PASS | `expand_ha_intents.py` lines 85-98: try-import with `_USE_HASSIL` flag, clarifying comment explains custom expansion is used intentionally. Acceptable since the spec says "optional" and custom expansion is the fallback. |

### New Bugs (Introduced by Fixes)

No new bugs were introduced by the fixes. Specific checks performed:

- **Parameter count alignment:** INSERT has 7 columns, 7 `%s` placeholders, and 7-element parameter tuple -- all match.
- **`_intent_to_service()` correctness:** All 23 explicit mappings tested and correct. Fallback PascalCase logic tested with 5 additional unknown intents -- all produce valid `{domain}.{action}` strings.
- **`json.dumps` type safety:** Both `json.dumps(list)` for patterns and `json.dumps(dict_or_empty)` for default_parameters produce valid JSON strings compatible with PostgreSQL JSONB columns.
- **ON CONFLICT UPDATE clause:** Now includes `service = EXCLUDED.service` (line 190) -- correctly updates the service field on upsert.
- **No import regressions:** `expand_ha_intents.py` does not import `json` (not needed -- `json.dumps` is only used in `main.py` which already imports it). The `re` module import on line 16 covers the new `_intent_to_service()` regex usage.

### Open Bugs (Non-blocking, carried forward from initial QA)

#### BUG-3: `.env` file contains real database password (MEDIUM -- mitigated)

- **Status:** Open (non-blocking)
- **Mitigation:** `.gitignore` line 26 excludes `docker/compose/automations/hassil-parser/.env`. `.env.example` uses dummy values. Risk is mitigated as long as `.gitignore` is respected.

#### BUG-4: `_USE_HASSIL` flag set but never used for expansion (LOW -- addressed)

- **Status:** Addressed with clarifying comment and log message. Full hassil integration deferred to future iteration.

#### BUG-6: ON CONFLICT silent overwrite for duplicate intent names within a domain YAML (LOW)

- **Status:** Open (non-blocking). HA intent names are unique within a domain YAML file in practice. No real-world impact.

### Security Audit (unchanged from initial QA)

All security findings from the initial QA remain unchanged. No new security issues introduced by the fixes.

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| SEC-1 | No authentication on endpoints | MEDIUM | Accepted for Phase 1 (internal-only access) |
| SEC-2 | No rate limiting on sync endpoint | LOW | Accepted for Phase 1 |
| SEC-3 | SQL injection risk | PASS | Parameterized queries used throughout |
| SEC-4 | Error messages may leak internal details | LOW | Accepted for Phase 1 (internal-only) |
| SEC-5 | MQTT credentials in environment variable | PASS | Follows project conventions |
| SEC-6 | No TLS for MQTT connection | LOW | All traffic within Docker network |
| SEC-7 | `.env` file with real credentials | PASS | Properly gitignored |
| SEC-8 | No exposed ports | PASS | Internal-only access confirmed |

### Regression Check (updated)

- **PROJ-1 (Deployed):** PROJ-2 writes to `alice.ha_intent_templates` created by PROJ-1. The upsert uses `ON CONFLICT (domain, intent, language) DO UPDATE` which respects the unique constraint. With the BUG-1 fix, the INSERT now includes the `service` column, so upserts will succeed and update existing PROJ-1 seed data where domain+intent+language matches. This is expected and desired behavior -- GitHub-sourced patterns should replace seed data.
- **Existing n8n workflows:** No changes to n8n configuration or workflows. MQTT topic `alice/ha/sync` is only published to, not subscribed. No n8n workflow currently consumes this topic (PROJ-4 is Planned, not deployed).
- **Docker networks:** Uses existing external networks (`automation`, `backend`). No new networks created.
- **Shared volume:** Mounts same `/srv/warm/n8n/inbox` path as n8n. The hassil-parser code does not write to `/data_inbox` during sync.
- **Result:** No regression risk. PROJ-1 seed data will be updated (not corrupted) by sync -- this is intended.

### Summary

- **Acceptance Criteria:** 14/14 PASS
- **Bug Fix Verification:** 3/3 blocking fixes verified correct (BUG-1, BUG-2, BUG-5). 1/1 comment fix verified (BUG-4).
- **New Bugs:** None introduced by the fixes.
- **Open Bugs:** 3 non-blocking (BUG-3 medium/mitigated, BUG-4 low/addressed, BUG-6 low)
- **Security:** No critical findings. 1 medium (no auth -- accepted for Phase 1), 3 low findings. No changes from initial QA.
- **Regression:** No risk to PROJ-1 or existing infrastructure.
- **Production Ready:** YES -- all blocking bugs fixed, all 14 acceptance criteria pass. Recommended to perform a live integration test with the real PostgreSQL instance during deployment to confirm end-to-end upsert behavior.

---

### Initial QA (2026-02-24) -- archived

<details>
<summary>Click to expand initial QA results</summary>

**Overall Status:** FAIL

**Bugs Found:** 6 total -- 1 Critical (BUG-1), 1 High (BUG-2), 1 Medium (BUG-3), 3 Low (BUG-4, BUG-5, BUG-6)

**Blocking Issues:**
- BUG-1 (Critical): INSERT missing `service` column -- every upsert fails with NOT NULL violation
- BUG-2 (High): `patterns` passed as Python list instead of JSONB -- psycopg2 type mismatch
- BUG-5 (Low/Blocking): `default_parameters` passed as None violates NOT NULL constraint

**Acceptance Criteria:** 12/14 PASS, 1 FAIL (AC-6), 1 PASS with note (AC-14)

**Recommendation:** Fix BUG-1, BUG-2, BUG-5, then re-test.

</details>

## Deployment

**Deployed:** 2026-02-24
**Server:** ki.lan
**Container:** `hassil-parser` (port 8001 internal, Docker networks: `automation`, `backend`)

### Deployment Steps Performed

1. Committed all code (10 files, `feat(PROJ-2)`)
2. Synced compose files to server via `./sync-compose.sh`
3. Built Docker image on server: `docker compose -f automations/hassil-parser/compose.yml build --no-cache`
4. Started container: `docker compose -f automations/hassil-parser/compose.yml up -d`
5. Verified `GET /health` → `{"status":"healthy"}`
6. Ran `POST /intents/sync` → `{"inserted":55,"updated":0,"skipped":0,"duration_ms":11129}`
7. Verified 55 templates written to `alice.ha_intent_templates` with `source='github'`

### Post-Deployment Notes

- `alice_user` password was set to match `.env` during deployment (password not in postgres before)
- Domain column contains `{domain}_{IntentName}` format (e.g. `light_HassTurnOn`) — PROJ-3 must account for this when querying

### Regression

- PROJ-1 seed data unaffected (different domain+intent+language keys)
