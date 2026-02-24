# PROJ-1: HA Intent Infrastructure (DB-Schema & Weaviate Collection)

## Status: In Review
**Created:** 2026-02-23
**Last Updated:** 2026-02-24

## Dependencies
- None (Phase 1.1 already deployed: alice.* schema exists, Weaviate running)

## Overview

Extends the existing PostgreSQL `alice` schema and Weaviate instance with the data structures needed for fast HA intent recognition. This is the foundation for all Phase 1.2 features.

## User Stories

- As a developer, I want a `alice.ha_intent_templates` table so that intent pattern metadata can be stored and managed per domain.
- As a developer, I want a `alice.ha_entities` table so that the current HA entity registry is tracked and compared across syncs.
- As a developer, I want a `alice.ha_sync_log` table so that every sync run is auditable.
- As a developer, I want a `HAIntent` Weaviate collection so that utterances can be matched semantically to HA service calls.
- As a developer, I want n8n environment variables for intent tuning so that thresholds can be adjusted without code changes.

## Acceptance Criteria

- [ ] `alice.ha_intent_templates` table created with columns: `id`, `domain`, `intent`, `service`, `patterns` (JSONB), `default_parameters` (JSONB), `requires_confirmation`, `language`, `priority`, `is_active`, `source`, `notes`, `created_at`, `updated_at`
- [ ] `alice.ha_entities` table created with columns: `id`, `entity_id` (UNIQUE), `domain`, `friendly_name`, `area_id`, `area_name`, `aliases` (JSONB), `device_class`, `supported_features`, `last_seen_at`, `is_active`, `weaviate_synced`, `intents_count`, `created_at`, `updated_at`
- [ ] `alice.ha_sync_log` table created with columns: `id`, `sync_type`, `trigger_source`, `entities_found`, `entities_added`, `entities_removed`, `entities_updated`, `intents_generated`, `intents_removed`, `duration_ms`, `status`, `error_message`, `details` (JSONB), `started_at`, `completed_at`
- [ ] All indexes created (domain, entity_id, is_active + weaviate_synced)
- [ ] Weaviate `HAIntent` collection created with correct schema (utterance vectorized, all other fields with `skip: true`)
- [ ] A test insert + `nearText` query against `HAIntent` in Weaviate succeeds
- [ ] n8n environment variables added: `INTENT_MIN_CERTAINTY=0.82`, `INTENT_MAX_RESULTS=3`, `OLLAMA_MODEL=qwen3:14b`
- [ ] MQTT topic `alice/ha/sync` reachable from n8n (credential configured)

## Edge Cases

- If `alice.ha_intent_templates` or `alice.ha_entities` already exist from a prior migration attempt, the SQL must use `CREATE TABLE IF NOT EXISTS` to be idempotent.
- If the `HAIntent` Weaviate collection already exists, the init script must skip creation gracefully (check via `GET /v1/schema/HAIntent` first).
- The `patterns` JSONB column must accept arrays of strings with `{name}`, `{area}`, `{where}` placeholders — validated by constraint or app logic.
- `requires_confirmation` defaults to `FALSE`; domains `lock` and `alarm_control_panel` must have this set to `TRUE` in seed data.

## Technical Requirements

- SQL must run in the `alice` schema (not public)
- Weaviate vectorizer: `text2vec-transformers`, distance: `cosine`
- Only the `utterance` property is vectorized; all other properties use `"skip": true`
- Language filter support: `language` property on `HAIntent` is filterable

---

## Tech Design (Solution Architect)

### Summary

This feature is **pure data infrastructure** — no UI, no n8n workflow logic. It creates the storage layer that all subsequent Phase 1.2 features (PROJ-2, PROJ-3, PROJ-4) depend on. It consists of three parts: two new PostgreSQL tables + one existing table extension, one new Weaviate collection, and three n8n environment variables.

---

### A) Data Layer Structure

```text
alice (PostgreSQL Schema — already exists)
+-- alice.ha_intent_templates  [NEW]
|   Purpose: Stores the "vocabulary" of HA commands.
|   One row = one intent type (e.g. "turn on lights in room X")
|   Key data: domain, service, patterns (JSONB array), default params,
|             confirmation flag, language, active/inactive toggle
|
+-- alice.ha_entities          [NEW]
|   Purpose: Mirror of the current HA entity registry.
|   One row = one HA device/sensor (e.g. light.wohnzimmer_decke)
|   Key data: entity_id, domain, friendly_name, area, aliases,
|             weaviate sync status, intent count
|
+-- alice.ha_sync_log          [NEW]
    Purpose: Audit trail for every sync run.
    One row = one sync event (adds/removes/updates counts, duration, errors)

Weaviate (Vector DB — already running)
+-- HAIntent                   [NEW COLLECTION]
    Purpose: Semantic search index for matching user utterances
             to HA service calls.
    Vectorized field: utterance (the natural language phrase)
    All other fields: stored but not vectorized (skip: true)
    Key fields: utterance, entityId, domain, service, parameters (JSON text),
                language, intentTemplate, certaintyThreshold
```

---

### B) Relationship Between Components

```text
User speaks/types
       ↓
alice.ha_intent_templates  ──generates──►  HAIntent (Weaviate)
  (pattern definitions)                    (vectorized utterances)

alice.ha_entities          ──informs──►   HAIntent (Weaviate)
  (live entity registry)                  (one entry per entity×intent combo)

alice.ha_sync_log
  (records each sync run: how many added/removed/updated)
```

The key insight: `ha_intent_templates` defines **what kinds of things** Alice can do; `ha_entities` defines **which specific devices** exist; the cross-product of both populates `HAIntent` in Weaviate with concrete, vectorized utterances like *"Wohnzimmerlicht einschalten"* or *"Küche hell machen"*.

---

### C) Design Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Patterns stored as JSONB | `patterns TEXT[]` in JSONB | Allows template variables like `{name}`, `{area}` without a separate join table |
| Only `utterance` vectorized in Weaviate | All other fields `skip: true` | Embedding only the natural language phrase keeps vectors clean; metadata is for filtering |
| `weaviate_synced` flag on `ha_entities` | Boolean per entity | Enables incremental sync — only re-push entities that changed |
| `intents_count` on `ha_entities` | Denormalized counter | Avoids COUNT query on Weaviate during sync; updated by the sync process |
| `requires_confirmation` flag on templates | Defaults FALSE; TRUE for `lock`, `alarm_control_panel` | Safety-critical domains need explicit user confirmation before action |
| Idempotent SQL (`CREATE TABLE IF NOT EXISTS`) | Required by spec | Migration can be re-run safely without data loss |
| Weaviate collection check before creation | `GET /v1/schema/HAIntent` first | Prevents error if collection was partially created |
| Cosine distance in Weaviate | Same as `AliceMemory` | Consistent with existing project convention |

---

### D) Indexes

| Table | Index on | Reason |
| --- | --- | --- |
| `ha_intent_templates` | `domain`, `is_active` | Filter active templates by domain during sync |
| `ha_entities` | `entity_id` (UNIQUE), `domain`, `is_active + weaviate_synced` | Fast lookup by ID; partial sync queries |
| `ha_sync_log` | `started_at`, `sync_type` | Audit queries and last-run lookups |

---

### E) n8n Environment Variables

Three variables are added to n8n's configuration (not to any workflow logic — they are read as `$env.VARIABLE_NAME`):

| Variable | Value | Purpose |
| --- | --- | --- |
| `INTENT_MIN_CERTAINTY` | `0.82` | Minimum Weaviate cosine similarity score to accept a match |
| `INTENT_MAX_RESULTS` | `3` | How many candidate intents to retrieve per query |
| `OLLAMA_MODEL` | `qwen3:14b` | Model name used by PROJ-3 chat handler (set here to centralize config) |

---

### F) Deliverables

| # | Deliverable | Type |
| --- | --- | --- |
| 1 | `sql/ha-intent-infrastructure.sql` | New SQL migration file |
| 2 | `schemas/ha-intent.json` | New Weaviate collection schema file |
| 3 | Updated `scripts/init-weaviate-schema.sh` | Adds HAIntent to existing init script |
| 4 | n8n env vars documented in `.env.n8n.example` | Config documentation |

---

### G) Dependencies

- Phase 1.1 already deployed: `alice.*` schema exists, Weaviate running, n8n running
- No changes to existing tables (purely additive)
- No frontend changes
- No new Docker containers

## QA Test Results (Final Review)

**Tested:** 2026-02-24
**Artifacts reviewed:** `sql/ha-intent-infrastructure.sql`, `schemas/ha-intent.json`, `scripts/init-weaviate-schema.sh`, `scripts/init-weaviate-schema.py`, `.env.n8n.example`, `.gitignore`, `CLAUDE.md`
**Tester:** QA Engineer (AI)
**Review type:** Final / conclusive QA pass

### Acceptance Criteria Status

#### AC-1: `alice.ha_intent_templates` table
- [x] Table created with `CREATE TABLE IF NOT EXISTS` (idempotent)
- [x] All 14 required columns present: `id`, `domain`, `intent`, `service`, `patterns` (JSONB), `default_parameters` (JSONB), `requires_confirmation`, `language`, `priority`, `is_active`, `source`, `notes`, `created_at`, `updated_at`
- [x] Column types match spec (SERIAL PK, VARCHAR, JSONB, BOOLEAN, SMALLINT, TEXT, TIMESTAMPTZ)
- [x] Sensible defaults on all columns (patterns='[]', default_parameters='{}', requires_confirmation=FALSE, language='de', priority=50, is_active=TRUE, source='seed')
- **Result: PASS**

#### AC-2: `alice.ha_entities` table
- [x] Table created with `CREATE TABLE IF NOT EXISTS` (idempotent)
- [x] All 14 required columns present: `id`, `entity_id` (UNIQUE), `domain`, `friendly_name`, `area_id`, `area_name`, `aliases` (JSONB), `device_class`, `supported_features`, `last_seen_at`, `is_active`, `weaviate_synced`, `intents_count`, `created_at`, `updated_at`
- [x] `entity_id` has UNIQUE constraint inline
- **Result: PASS**

#### AC-3: `alice.ha_sync_log` table
- [x] Table created with `CREATE TABLE IF NOT EXISTS` (idempotent)
- [x] All 14 required columns present: `id`, `sync_type`, `trigger_source`, `entities_found`, `entities_added`, `entities_removed`, `entities_updated`, `intents_generated`, `intents_removed`, `duration_ms`, `status`, `error_message`, `details` (JSONB), `started_at`, `completed_at`
- [x] `status` has CHECK constraint limiting to valid values ('running', 'success', 'partial', 'error')
- **Result: PASS**

#### AC-4: All indexes created
- [x] `idx_ha_intent_templates_domain` on `(domain)`
- [x] `idx_ha_intent_templates_is_active` on `(is_active)`
- [x] `idx_ha_intent_templates_domain_active` partial index on `(domain, is_active) WHERE is_active = TRUE`
- [x] `idx_ha_entities_domain` on `(domain)`
- [x] `idx_ha_entities_is_active` on `(is_active)`
- [x] `idx_ha_entities_sync_pending` partial index on `(is_active, weaviate_synced) WHERE is_active = TRUE AND weaviate_synced = FALSE`
- [x] `idx_ha_sync_log_started_at` on `(started_at DESC)`
- [x] `idx_ha_sync_log_sync_type` on `(sync_type)`
- [x] `entity_id` UNIQUE constraint (implicit unique index)
- **Result: PASS**

#### AC-5: Weaviate `HAIntent` collection schema
- [x] `schemas/ha-intent.json` exists with class name `HAIntent`
- [x] Vectorizer: `text2vec-transformers`
- [x] Distance: `cosine`
- [x] `utterance` property: `skip: false` (vectorized), `indexSearchable: true`
- [x] `entityId` property: `skip: true`, `indexFilterable: true`
- [x] `domain` property: `skip: true`, `indexFilterable: true`
- [x] `service` property: `skip: true`
- [x] `parameters` property: `skip: true`
- [x] `language` property: `skip: true`, `indexFilterable: true` (filterable as required)
- [x] `intentTemplate` property: `skip: true`, `indexFilterable: true`
- [x] `certaintyThreshold` property: number type, no explicit `skip` in moduleConfig (acceptable -- number types are not vectorized by text2vec-transformers by default)
- **Result: PASS**

#### AC-6: Test insert + nearText query against HAIntent succeeds

- [ ] No test script, test log, or verification artifact exists to demonstrate that a test insert and nearText query were performed and succeeded

- **Result: FAIL** (no evidence of verification -- see BUG-4)

#### AC-7: n8n environment variables
- [x] `INTENT_MIN_CERTAINTY=0.82` documented in `.env.n8n.example`
- [x] `INTENT_MAX_RESULTS=3` documented in `.env.n8n.example`
- [x] `OLLAMA_MODEL=qwen3:14b` documented in `.env.n8n.example`
- **Result: PASS**

#### AC-8: MQTT topic `alice/ha/sync` reachable from n8n

- [ ] No evidence that MQTT credential was configured or that the topic was tested for reachability

- **Result: FAIL** (no verification artifact -- see BUG-5)

### Edge Cases Status

#### EC-1: Idempotent SQL (re-runnable)
- [x] All three tables use `CREATE TABLE IF NOT EXISTS`
- [x] All indexes use `CREATE INDEX IF NOT EXISTS`
- [x] Triggers use `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`
- [x] RLS policies use `DROP POLICY IF EXISTS` before `CREATE POLICY`
- [x] Seed data uses `ON CONFLICT (domain, intent, language) DO NOTHING`
- [ ] BUG: `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` (line 197) is only supported in PostgreSQL 16+. If the target is PostgreSQL < 16, re-running the SQL will fail with "constraint already exists" (see BUG-1)
- **Result: CONDITIONAL PASS** (depends on PostgreSQL version)

#### EC-2: Weaviate collection already exists
- [x] `init-weaviate-schema.sh` checks `GET /v1/schema/HAIntent` before creation and skips if exists
- [x] `init-weaviate-schema.py` calls `collection_exists()` before creation and skips if exists
- **Result: PASS**

#### EC-3: Patterns JSONB accepts arrays with placeholders
- [x] Seed data demonstrates arrays of strings with `{name}`, `{area}`, `{where}` placeholders
- [x] Column defined as `JSONB NOT NULL DEFAULT '[]'`
- [ ] NOTE: No CHECK constraint or validation function enforces valid placeholder names. Spec says "validated by constraint or app logic" -- deferred to app logic. Acceptable.
- **Result: PASS**

#### EC-4: `requires_confirmation` defaults FALSE; lock and alarm TRUE in seeds
- [x] Column defaults to `FALSE`
- [x] `lock.lock` seed: `requires_confirmation = TRUE`
- [x] `lock.unlock` seed: `requires_confirmation = TRUE`
- [x] `alarm_control_panel.alarm_arm_away` seed: `requires_confirmation = TRUE`
- [x] `alarm_control_panel.alarm_disarm` seed: `requires_confirmation = TRUE`
- [x] All other domains default to `requires_confirmation = FALSE`
- **Result: PASS**

### Security Audit Results

- [x] No secrets committed: `.env.n8n.example` contains only dummy/example values
- [x] `.env.n8n` is listed in `.gitignore` (line 17) -- credential leakage risk mitigated (previously BUG-3, now FIXED)
- [ ] BUG: RLS policies on all three new tables use `USING (TRUE)` for ALL operations (SELECT, INSERT, UPDATE, DELETE). This provides zero access control -- any database role can read, modify, and delete all rows. While these are infrastructure/config tables, the policies are effectively no-ops (see BUG-2)
- [x] SQL injection: Not applicable (no user input processing in this feature)
- [x] No sensitive data exposed: Tables contain only device metadata and intent patterns
- [x] Seed data uses parameterized JSONB strings, no injection risk
- [ ] NOTE: `init-weaviate-schema.sh` intentionally does NOT use `set -e` (line 19 comment explains this is to allow error counting in the main loop). This is acceptable design but means individual curl failures do not abort the script. Error counting logic handles this appropriately.

### Bugs Found

#### BUG-1: `ADD CONSTRAINT IF NOT EXISTS` requires PostgreSQL 16+ (OPEN)

- **Severity:** High
- **Steps to Reproduce:**
  1. Run `sql/ha-intent-infrastructure.sql` on PostgreSQL < 16 (e.g., PostgreSQL 15)
  2. Run the same SQL a second time
  3. Expected: Idempotent execution, no errors
  4. Actual: `ERROR: syntax error at or near "IF"` on line 197 (`ALTER TABLE alice.ha_intent_templates ADD CONSTRAINT IF NOT EXISTS ...`)
- **File:** `/home/stan/Apps/development/alice/sql/ha-intent-infrastructure.sql` line 196-198
- **Fix suggestion:** Use a `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$` block, or check `pg_constraint` before adding
- **Priority:** Fix before deployment (blocks idempotency requirement on PG < 16)

#### BUG-2: RLS policies are permissive no-ops (USING TRUE on all operations) (OPEN)

- **Severity:** Low
- **Steps to Reproduce:**
  1. Inspect RLS policies on `ha_intent_templates`, `ha_entities`, `ha_sync_log`
  2. All four policies (SELECT, INSERT, UPDATE, DELETE) on all three tables use `USING (TRUE)` / `WITH CHECK (TRUE)`
  3. Expected: At minimum, write operations (INSERT, UPDATE, DELETE) should be restricted to admin roles or the n8n service account
  4. Actual: Any database role can perform any operation on these tables
- **File:** `/home/stan/Apps/development/alice/sql/ha-intent-infrastructure.sql` lines 58-74, 119-135, 170-186
- **Note:** RLS is enabled (good), but the policies are all-permissive. For infrastructure/config tables this may be intentional for Phase 1, but should be tightened in Phase 3. Not blocking deployment.
- **Priority:** Fix in Phase 3 (security hardening)

#### BUG-3: CLAUDE.md architecture diagram references old model name (OPEN)

- **Severity:** Low
- **Steps to Reproduce:**
  1. Read `CLAUDE.md` line 7: correctly says `qwen3:14b`
  2. Read `CLAUDE.md` line 46 (architecture diagram): still says `qwen2.5:14b`
  3. Expected: Consistent model name across the file
  4. Actual: Two different model names in the same file
- **File:** `/home/stan/Apps/development/alice/CLAUDE.md` line 46
- **Fix suggestion:** Update the architecture diagram on line 46 from `qwen2.5:14b` to `qwen3:14b`
- **Priority:** Fix in next sprint (documentation consistency)

#### BUG-4: No test/verification artifacts for AC-6 (Weaviate test query) (OPEN)
- **Severity:** Medium
- **Steps to Reproduce:**
  1. AC-6 requires: "A test insert + nearText query against HAIntent in Weaviate succeeds"
  2. Expected: A test script, test log output, or documented manual test result
  3. Actual: No artifacts exist in the repository to verify this criterion was met
- **Priority:** Verify during deployment (run a manual test insert + nearText query and document the result)

#### BUG-5: No verification artifacts for AC-8 (MQTT reachability) (OPEN)
- **Severity:** Medium
- **Steps to Reproduce:**
  1. AC-8 requires: "MQTT topic alice/ha/sync reachable from n8n (credential configured)"
  2. Expected: Evidence that MQTT credential was configured and topic was tested
  3. Actual: No artifacts exist to verify this criterion was met
- **Priority:** Verify during deployment (configure MQTT credential in n8n and test publish/subscribe on `alice/ha/sync`)

### Previously Reported Bugs -- Now Resolved

| Bug | Description | Status |
| --- | --- | --- |
| Former BUG-2 | Python init script missing `ha-intent.json` | FIXED -- `init-weaviate-schema.py` line 39 now includes `"ha-intent.json"` |
| Former BUG-3 | `.env.n8n` not in `.gitignore` | FIXED -- `.gitignore` line 17 now includes `.env.n8n` |
| Former BUG-5 | OLLAMA_MODEL mismatch (CLAUDE.md vs spec) | PARTIALLY FIXED -- CLAUDE.md line 7 updated to `qwen3:14b`, but architecture diagram line 46 still says `qwen2.5:14b` (see new BUG-3) |

### Cross-Browser / Responsive Testing
- Not applicable: PROJ-1 is a pure data infrastructure feature with no UI components.

### Regression Testing
- No deployed features exist yet (INDEX.md shows no "Deployed" status features)
- PROJ-1 is purely additive (new tables, new Weaviate collection, new env vars)
- No changes to existing tables in `init-postgres.sql`
- No changes to existing Weaviate collection schemas
- **Result: No regression risk identified**

### Summary
- **Acceptance Criteria:** 6/8 passed, 2 failed (AC-6 and AC-8: missing runtime verification)
- **Bugs Found:** 5 open (0 critical, 1 high, 2 medium, 2 low)
- **Previously Fixed:** 2 bugs fully resolved, 1 partially resolved
- **Security:** 1 low-severity finding (BUG-2: permissive RLS, deferred to Phase 3)
- **Production Ready:** NO
- **Blocking issues:** BUG-1 (PG version compat for idempotency), BUG-4/BUG-5 (AC-6 and AC-8 unverified)
- **Recommendation:** Fix BUG-1 (use PG-compatible idempotent constraint creation). Then during deployment, verify AC-6 (Weaviate test insert + nearText) and AC-8 (MQTT reachability) manually and document results. BUG-3 (CLAUDE.md diagram) is a quick doc fix. BUG-2 (RLS) can wait for Phase 3.

## Deployment

**Deployed:** 2026-02-24
**Environment:** Production (`ki.lan` via VPN)

### Steps Executed

1. **BUG-1 Fix** — `sql/ha-intent-infrastructure.sql` line 195-198: replaced `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` (not valid in any PG version) with a `DO $$ BEGIN ... EXCEPTION WHEN duplicate_table THEN NULL; END $$` block. SQL is now idempotent on PG 12+.

2. **PostgreSQL migration** — Applied `sql/ha-intent-infrastructure.sql` via `docker exec postgres psql -U alice_user -d alice`. Result:
   - `alice.ha_intent_templates` created — 19 seed rows (8 domains: alarm_control_panel×2, climate×3, cover×2, light×3, lock×2, media_player×3, switch×2, vacuum×2)
   - `alice.ha_entities` created — empty, ready for PROJ-4 sync
   - `alice.ha_sync_log` created — empty, ready for audit logging
   - All indexes and RLS policies applied

3. **Weaviate HAIntent collection** — Created via `POST /v1/schema` from within weaviate container. Collection verified with `GET /v1/schema/HAIntent`.

4. **AC-6 — Weaviate nearText test** — `t2v-transformers` container moved from TITAN X (sm_61, incompatible with PyTorch min. sm_70) to RTX 3090 (sm_86). After restart: insert HTTP 200, nearText query returned match with certainty 0.976 — well above the 0.82 threshold. `multi2vec-clip` remains on TITAN X (unaffected). ✅

5. **n8n environment variables** — Added to `/srv/compose/automations/n8n/compose.yml` and container recreated:
   - `INTENT_MIN_CERTAINTY=0.82` ✅
   - `INTENT_MAX_RESULTS=3` ✅
   - `OLLAMA_MODEL=qwen3:14b` ✅

6. **AC-8 — MQTT topic `alice/ha/sync`** — Verified manually from desktop:
   - `mosquitto_pub -h mqtt.lan -u stan -t alice/ha/sync -m ac8-test` → OK
   - `mosquitto_sub -h mqtt.lan -u stan -t alice/ha/sync -C 1 -W 5` → received `ac8-test`
   - Topic is reachable and functional ✅

### Open Items Post-Deployment

| Item                                                              | Severity | Action                                                                                             |
| ----------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------- |
| CUDA incompatibility on TITAN X Pascal (`weaviate-transformers`)  | High     | Replace container image with CPU-compatible or sm_61 build — affects all Weaviate nearText queries |
| BUG-2: RLS policies are all-permissive (`USING TRUE`)             | Low      | Tighten in Phase 3 security hardening                                                              |
