# PROJ-3: HA-First Chat Handler with Intent Routing

## Status: Deployed

**Created:** 2026-02-23
**Last Updated:** 2026-02-25

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — Weaviate `HAIntent` collection must be populated
- Requires: PROJ-2 (FastAPI Intent Helper) — templates must be loaded into PostgreSQL/Weaviate

## Overview

Extends the existing `alice-chat-handler` n8n workflow with a fast HA path. Instead of routing every request through the LLM, the workflow first tries to recognize Home Assistant intents via Weaviate semantic search. If all parts of the input are HA commands, they are executed in parallel in < 200ms — without any LLM call. Mixed inputs (HA + question) use a hybrid path. Unknown inputs fall through to the existing LLM path.

## User Stories

- As Andreas, I want to say "Mach das Wohnzimmerlicht an" and have the light turn on in under 200ms so that the response feels instant.
- As Andreas, I want to say "Dimme das Licht und schalte den Fernseher ein" and have both happen at the same time so that multi-command inputs work naturally.
- As Andreas, I want to say "Mach das Licht an und was ist das Wetter?" and get both a HA action AND a chat answer so that mixed inputs work seamlessly.
- As Andreas, I want to say "Erzähl mir einen Witz" and get a normal LLM answer so that non-HA inputs still work as before.
- As a developer, I want every request path (HA_FAST, HYBRID, LLM_ONLY) logged in `alice.messages` so that all interactions are traceable.
- As a developer, I want Prometheus-compatible latency metrics per path so that I can verify the < 200ms target is met.

## Acceptance Criteria

- [ ] `alice-chat-handler` workflow contains a **Sentence Splitter** step that splits on: "und dann", "und danach", "und außerdem", "und", "dann", "danach", "außerdem", "sowie", "zusätzlich", "auch noch", `,`, `.`
- [ ] Sentence Splitter filters out parts shorter than 4 characters and strips leading filler words (bitte, mal, noch, auch)
- [ ] After splitting, **parallel Weaviate nearText queries** run for all parts simultaneously (Promise.all)
- [ ] Intent results with certainty below `INTENT_MIN_CERTAINTY` (default 0.82) are treated as non-HA
- [ ] **HA_FAST path** is taken when ALL parts have a recognized HA intent — no LLM call
- [ ] **LLM_ONLY path** is taken when NO part has a recognized HA intent — existing chat logic unchanged
- [ ] **HYBRID path** is taken when SOME parts are HA intents — HA actions execute first (parallel), then remaining text goes to LLM
- [ ] HA service calls in HA_FAST and HYBRID paths execute in parallel (Promise.all)
- [ ] HA_FAST path responds in < 200ms end-to-end (measured Webhook → Response)
- [ ] Multi-intent HA_FAST path (2-3 commands) responds in < 400ms
- [ ] Template-based response is generated for HA results (e.g. "Wohnzimmerlicht eingeschaltet, Fernseher eingeschaltet.")
- [ ] `requires_confirmation = true` intents (lock, alarm) return a confirmation question instead of executing
- [ ] HA API errors (timeout, 401, entity not found) return a user-friendly German error message
- [ ] Weaviate unavailable → automatic fallback to LLM_ONLY path (no crash)
- [ ] All requests (all paths) saved to `alice.messages` with `session_id`, `user_id`, `role`, `content`, `tool_calls`, `tool_results`
- [ ] Path taken (`HA_FAST` / `HYBRID` / `LLM_ONLY`) recorded in `tool_results` JSONB for analytics

## Edge Cases

- Input is a single word like "Licht" — Splitter passes it through as one part; intent search runs normally.
- All parts recognized as HA but one fails at execution — partial success: executed actions confirmed, failed action reported.
- HA token expired (HTTP 401) — return "HA-Verbindung fehlgeschlagen, bitte Token prüfen" and log error.
- Entity in intent not found in HA (HTTP 404 or empty result) — return "Ich konnte [entity] nicht finden."
- User input is empty string — return early with validation error before any Weaviate/LLM call.
- Weaviate returns multiple intents with similar certainty — use highest certainty; if tie, use higher `priority` from intent metadata.
- HYBRID path: HA actions complete but LLM call fails — return HA result + generic error for the chat part.

## Technical Requirements

- Performance: HA_FAST < 200ms, Multi-HA < 400ms, LLM < 3s (P95)
- Certainty threshold configurable via n8n env var `INTENT_MIN_CERTAINTY`
- No breaking changes to the existing LLM_ONLY chat path

---

## Tech Design (Solution Architect)

### Summary

This feature extends the existing `alice-chat-handler` n8n workflow with a **three-path routing engine**. No new Docker containers, no schema changes, no frontend changes. Pure n8n workflow logic built on the already-deployed PROJ-1 and PROJ-2 infrastructure.

---

### A) Workflow Flow (Visual Tree)

```
alice-chat-handler (n8n Webhook POST /webhook/alice)
│
├── [0] Input Validation
│       └── empty string → return early, no further processing
│
├── [1] Sentence Splitter (Code node)
│       └── Split on: "und dann", "und danach", "und außerdem", "und",
│                     "dann", "danach", "außerdem", "sowie", "zusätzlich",
│                     "auch noch", ",", "."
│       └── Filter: parts < 4 chars removed, leading filler words stripped
│                   (bitte, mal, noch, auch)
│       └── Result: 1–N sentence parts (array)
│
├── [2] Parallel Intent Lookup (Weaviate nearText)
│       └── One query per sentence part — all run simultaneously
│       └── Each returns: intent data + certainty score
│       └── Score < INTENT_MIN_CERTAINTY (0.82) → "no match"
│       └── Weaviate unavailable → ALL parts marked "no match" → LLM fallback
│
├── [3] Path Router (Switch node)
│       ├── ALL parts matched  → HA_FAST path
│       ├── SOME parts matched → HYBRID path
│       └── NO parts matched   → LLM_ONLY path (existing logic, unchanged)
│
├── [HA_FAST] ── all parts are HA commands ────────────────────────────────┐
│       ├── [4a] Confirmation check                                         │
│       │       └── requires_confirmation = true → return question,         │
│       │           do NOT execute, save to alice.messages                  │
│       ├── [4b] Parallel HA service calls (Promise.all in Code node)       │
│       │       └── Calls alice-tool-ha for each command simultaneously     │
│       │       └── Partial failure: succeeded confirmed, failed reported   │
│       └── [4c] Template response builder                                  │
│               └── e.g. "Wohnzimmerlicht eingeschaltet, Fernseher an."    │
│                                                                            │
├── [HYBRID] ── mix of HA + non-HA parts ───────────────────────────────────┤
│       ├── [5a] Parallel HA service calls (same as 4b)                     │
│       └── [5b] Non-HA parts → LLM call (Ollama qwen3:14b)                │
│               └── HA actions complete first, LLM result appended          │
│               └── LLM failure → HA result + generic error for chat part   │
│                                                                            │
└── [LLM_ONLY] ── no HA match ──────────────────────────────────────────────┤
        └── [6] Existing chat logic (memory, tool-use, LLM response)        │
                Unchanged from current implementation                        │
                                                                             │
[All paths] ─────────────────────────────────────────────────────────────────┘
    └── [7] Save to alice.messages
            session_id, user_id, role, content, tool_calls,
            tool_results JSONB includes path_taken: HA_FAST | HYBRID | LLM_ONLY
```

---

### B) Three-Path Routing Decision Table

| Situation | Example input | Path | LLM called? |
| --- | --- | --- | --- |
| Single HA command | "Mach das Licht an" | HA_FAST | No |
| Multi HA commands | "Licht an und TV ein" | HA_FAST | No |
| HA + question | "Licht an und was ist das Wetter?" | HYBRID | Yes (question part only) |
| Pure question/chat | "Erzähl mir einen Witz" | LLM_ONLY | Yes |
| Confirmation-required | "Schließ das Schloss" | HA_FAST (blocked) | No — returns question |
| Weaviate unavailable | any input | LLM_ONLY | Yes (automatic fallback) |

---

### C) Data Flow

```
READ:
  - Weaviate HAIntent collection (vectors + entity/service/parameters metadata)
  - $env.INTENT_MIN_CERTAINTY (threshold: 0.82)
  - $env.INTENT_MAX_RESULTS (candidates per query: 3)

WRITTEN:
  - alice.messages (PostgreSQL) — every request on every path:
      session_id, user_id, role, content, tool_calls,
      tool_results.path_taken: "HA_FAST" | "HYBRID" | "LLM_ONLY"
      tool_results includes intents matched, certainty scores, HA API results

EXTERNAL CALLS:
  - Weaviate nearText API     (step 2 — intent lookup)
  - Home Assistant REST API   (steps 4b, 5a — service calls)
  - Ollama qwen3:14b          (steps 5b, 6 — LLM inference, HYBRID + LLM_ONLY)
```

---

### D) Design Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Extend existing workflow vs. new one | Extend `alice-chat-handler` | No breaking change to the webhook endpoint; one workflow to maintain |
| Sentence splitting | JavaScript Code node | n8n has no built-in text splitter; Code node handles all 10+ delimiters cleanly |
| Parallel Weaviate queries | SplitInBatches + parallel branch | All parts searched simultaneously — critical for the <200ms target |
| Path router | Switch node on match counts | Visual, debuggable branching on the n8n canvas |
| Parallel HA calls | Promise.all inside a single Code node | Native parallel n8n nodes add overhead; Code node executes all HA calls at once |
| `requires_confirmation` guard | Check node before any HA execution | Lock/alarm domains must never auto-execute — runs even in the fast path |
| Weaviate fallback | Catch-error node → LLM_ONLY | If Weaviate is down, Alice degrades gracefully instead of crashing |
| Metrics in `tool_results` JSONB | Reuse existing message schema | No new table needed; path + latency data queryable via PG JSON operators |
| Template-based HA responses | Fixed template strings per intent | No LLM call = no latency; responses are deterministic |

---

### E) Deliverables

```
alice-chat-handler (existing workflow — modified in n8n)
├── NEW: Sentence Splitter node (Code)
├── NEW: Parallel Weaviate nearText nodes
├── NEW: Path Router (Switch node)
├── NEW: HA_FAST branch (Code node with Promise.all + template builder)
├── NEW: HYBRID branch (parallel HA calls + LLM call)
├── UNCHANGED: LLM_ONLY branch (existing logic)
└── NEW: Path logger (writes path_taken to tool_results before message save)

alice-tool-ha (existing sub-workflow — no changes required)
```

No new n8n credentials. All connections (Weaviate, PostgreSQL, HA, Ollama) already exist.

---

### F) Performance Targets

| Target | Mechanism |
| --- | --- |
| HA_FAST < 200ms | Parallel Weaviate queries + parallel HA calls; zero LLM invocation |
| Multi-HA (2–3 cmds) < 400ms | Promise.all — N commands do not queue |
| LLM_ONLY < 3s P95 | Unchanged; Ollama qwen3:14b is already the bottleneck |

---

### G) No New Dependencies

No new npm packages, Docker containers, database tables, or Weaviate collections. All infrastructure is already deployed (PROJ-1 + PROJ-2).

## QA Test Results

**Tested:** 2026-02-25
**Artifact Reviewed:** `workflows/core/alice-chat-handler.json` (25 nodes, 21 connections, version 97)
**Tester:** QA Engineer (AI)
**Review Type:** Code-level review of n8n workflow JSON (no live environment test -- see note at end)

---

### Acceptance Criteria Status

#### AC-1: Sentence Splitter splits on all specified delimiters
- [x] Node `Sentence Splitter` (id: `node-sentence-splitter`) exists as a Code node
- [x] DELIMITERS array contains all 10 specified delimiters: `"und dann"`, `"und danach"`, `"und au\u00dferdem"`, `"auch noch"`, `"sowie"`, `"zus\u00e4tzlich"`, `"danach"`, `"au\u00dferdem"`, `"dann"`, `"und"`, `","`, `"."`
- [x] Splitting is case-insensitive (`'gi'` flag in RegExp)
- [x] Delimiters are ordered longest-first to avoid partial matches (e.g., "und dann" before "und")
- **Result: PASS**

#### AC-2: Sentence Splitter filters short parts and strips filler words
- [x] Filter: `p.length >= 4` removes parts shorter than 4 characters
- [x] FILLER_WORDS array contains: `"bitte"`, `"mal"`, `"noch"`, `"auch"`, `"doch"`
- [ ] BUG: Spec says filler words are `(bitte, mal, noch, auch)` -- implementation adds `"doch"` which is NOT in the spec. This is a minor addition, not a failure, but deviates from spec.
- [x] Filler stripping is recursive (while loop until no more changes)
- [x] Filler stripping only removes leading fillers (uses `^` anchor in regex)
- [x] Fallback: if all parts are filtered out, the original input is used as a single part
- **Result: PASS** (extra filler word "doch" is harmless)

#### AC-3: Parallel Weaviate nearText queries via Promise.all
- [x] Intent Lookup node uses `await Promise.all(parts.map(p => queryIntent(p)))` -- all queries execute simultaneously
- [x] Each query sends a GraphQL `nearText` request to Weaviate with the sentence part as concept
- **Result: PASS**

#### AC-4: Certainty threshold respects INTENT_MIN_CERTAINTY
- [x] Threshold reads from `$env.INTENT_MIN_CERTAINTY` with default `0.82`
- [x] Results below threshold treated as `{ matched: false }` with the actual certainty stored
- [x] Uses `candidates.find(c => (c._additional?.certainty || 0) >= CERTAINTY_THRESHOLD)` -- first candidate above threshold is used
- [ ] BUG: The `find()` method returns the FIRST candidate above threshold, not the one with HIGHEST certainty. If Weaviate returns results sorted by certainty (descending, which is the default), this works correctly. But the code does not explicitly sort, so it depends on Weaviate's default ordering. See BUG-3.
- **Result: PASS** (works correctly given Weaviate's default descending-certainty ordering)

#### AC-5: HA_FAST path taken when ALL parts match
- [x] Path Router Switch node checks `$json.pathDecision === 'HA_FAST'`
- [x] Intent Lookup sets `pathDecision = 'HA_FAST'` when `matchedCount === results.length`
- [x] HA Fast Executor does NOT call the LLM -- only HA service calls
- **Result: PASS**

#### AC-6: LLM_ONLY path taken when NO parts match
- [x] Path Router Switch node checks `$json.pathDecision === 'LLM_ONLY'`
- [x] Intent Lookup sets `pathDecision = 'LLM_ONLY'` when `matchedCount === 0` (or Weaviate down)
- [x] LLM Only Prep reformats data for the existing AI Agent node
- [x] AI Agent connects to Ollama Chat Model
- **Result: PASS**

#### AC-7: HYBRID path taken when SOME parts match
- [x] Path Router Switch node checks `$json.pathDecision === 'HYBRID'`
- [x] Intent Lookup sets `pathDecision = 'HYBRID'` when `matchedCount > 0 && matchedCount < results.length`
- [x] Hybrid Executor executes HA calls for matched parts AND sends unmatched parts to LLM
- [x] HA actions and LLM call execute in parallel via `Promise.all([Promise.all(haIntents.map(...)), callOllama(llmParts)])`
- **Result: PASS**

#### AC-8: HA service calls execute in parallel (Promise.all)
- [x] HA Fast Executor: `await Promise.all(intents.map(i => callHA(i)))` -- parallel execution
- [x] Hybrid Executor: `await Promise.all([Promise.all(haIntents.map(i => callHA(i))), ...])` -- parallel execution
- **Result: PASS**

#### AC-9: HA_FAST path responds in < 200ms
- [ ] Cannot verify in code review alone -- requires live performance test
- [x] Architecture supports this target: no LLM call, parallel Weaviate + parallel HA calls, template response
- [ ] NOTE: HA_FAST path has 6 sequential n8n node hops after the HA call: Executor -> Save Message -> DB Insert -> Format Response -> Respond. The DB Insert (PostgreSQL write) adds non-trivial latency to the critical path. See BUG-5.
- **Result: CANNOT VERIFY** (requires live test with timing instrumentation)

#### AC-10: Multi-intent HA_FAST path responds in < 400ms
- [ ] Cannot verify in code review alone -- requires live performance test
- [x] Architecture supports this: Promise.all for both Weaviate queries and HA calls means latency is max(calls) not sum(calls)
- **Result: CANNOT VERIFY** (requires live test)

#### AC-11: Template-based response generated for HA results
- [x] `buildText()` function in HA Fast Executor generates templated German responses
- [x] Maps service names to German verbs: `turn_on` -> `eingeschaltet`, `turn_off` -> `ausgeschaltet`, `open` -> `geoeffnet`, `close` -> `geschlossen`, `start` -> `gestartet`, `return` -> `zurueckgeschickt`, default -> `ausgefuehrt`
- [x] Entity name extracted from `entityId`, cleaned (`.pop()` + underscores to spaces), capitalized
- [ ] BUG: Hybrid Executor's `haText()` function has fewer action mappings than HA Fast Executor's `buildText()`. Missing: `start` -> `gestartet`, `return` -> `zurueckgeschickt`. See BUG-1.
- **Result: PASS** (HA_FAST path is correct; HYBRID has reduced mappings -- see BUG-1)

#### AC-12: `requires_confirmation = true` intents return confirmation question
- [x] HA Fast Executor checks `needsConfirmation` array and returns early with a German confirmation question
- [x] Confirmation domains are `['lock', 'alarm_control_panel']` matching PROJ-1 spec
- [ ] BUG: In HA_FAST path, if ANY intent requires confirmation, ALL intents are blocked -- even non-confirmation intents. E.g., "Licht an und Schloss abschliessen" would block the light action too. See BUG-2.
- [x] Hybrid Executor correctly separates `confirmIntents` from `haIntents` and only blocks the confirmation ones (better behavior than HA_FAST)
- **Result: PARTIAL PASS** (HYBRID handles correctly; HA_FAST blocks all intents when any one requires confirmation -- see BUG-2)

#### AC-13: HA API errors return user-friendly German messages
- [x] HTTP 401 -> `"HA-Verbindung fehlgeschlagen, bitte Token pruefen."` (both HA_FAST and Hybrid)
- [x] HTTP 404 -> `"Ich konnte [entityId] nicht finden."` (both HA_FAST and Hybrid)
- [x] Other errors -> `"Fehler bei [entityId]."` (both HA_FAST and Hybrid)
- [x] HA call timeout set to 5000ms -- reasonable
- **Result: PASS**

#### AC-14: Weaviate unavailable triggers LLM_ONLY fallback
- [x] `queryIntent()` catch block returns `{ weaviateError: true }` on any error
- [x] `weaviateDown` is true when `results.every(r => r.weaviateError)`
- [x] When `weaviateDown`, `pathDecision = 'LLM_ONLY'` -- correct fallback
- [x] Weaviate queries have 3000ms timeout
- **Result: PASS**

#### AC-15: All requests saved to alice.messages with required fields
- [x] HA_FAST path: DB Insert HA Fast writes `session_id`, `user_id`, `role` (hardcoded "assistant"), `content`, `tool_results`
- [x] HYBRID path: DB Insert Hybrid writes same fields
- [x] LLM_ONLY path: DB Insert LLM writes same fields
- [ ] BUG: The `tool_calls` column is never populated by any path. The DB Insert nodes only write `session_id`, `user_id`, `role`, `content`, `tool_results`. The spec says "saved to alice.messages with session_id, user_id, role, content, tool_calls, tool_results". See BUG-4.
- [ ] BUG: The user's original message is NOT saved to `alice.messages` -- only the assistant's response is saved. There is no DB Insert for the `role: 'user'` message on ANY path. See BUG-6.
- **Result: FAIL** (tool_calls never written; user message not saved)

#### AC-16: Path taken recorded in tool_results JSONB
- [x] HA_FAST: `tool_results.path_taken = 'HA_FAST'`
- [x] HYBRID: `tool_results.path_taken = 'HYBRID'`
- [x] LLM_ONLY: `tool_results.path_taken = 'LLM_ONLY'`
- [x] All paths also record `latency_ms` for analytics
- [x] HA_FAST and HYBRID additionally record `intents_matched`, `certainty_scores`, `ha_results`
- **Result: PASS**

---

### Edge Cases Status

#### EC-1: Single word input like "Licht"
- [x] "Licht" has 5 chars, passes the `>= 4` filter
- [x] No delimiters to split on, so it becomes a single-part array `["Licht"]`
- [x] Intent lookup runs on that single part
- **Result: PASS**

#### EC-2: All parts match HA but one fails at execution (partial success)
- [x] `callHA()` returns `{ success: false, error: '...', msg: '...' }` for failures
- [x] `buildText()` iterates all results and includes error messages inline with success messages
- [x] Promise.all resolves even when individual HA calls fail (errors caught in try/catch per call)
- **Result: PASS**

#### EC-3: HA token expired (HTTP 401)
- [x] Returns `"HA-Verbindung fehlgeschlagen, bitte Token pruefen."` in both HA_FAST and Hybrid
- [x] Error is captured per-call, not workflow-level crash
- **Result: PASS**

#### EC-4: Entity not found (HTTP 404)
- [x] Returns `"Ich konnte [entityId] nicht finden."` in both HA_FAST and Hybrid
- **Result: PASS**

#### EC-5: Empty string input
- [x] Input Validator checks `!userMsg || !userMsg.content || userMsg.content.trim().length === 0`
- [x] Returns early with `{ __error: true, errorMsg: 'Leere Eingabe. Bitte gib etwas ein.' }`
- [x] Empty Input Check (If node) routes to Error Response -> Respond Error
- [x] No Weaviate or LLM call is made
- **Result: PASS**

#### EC-6: Multiple intents with similar certainty (tie-breaking via priority)
- [ ] BUG: The code uses `candidates.find()` which returns the first match above threshold. There is NO tie-breaking logic using `priority` from intent metadata. The spec says: "use highest certainty; if tie, use higher priority from intent metadata." Priority-based tie-breaking is not implemented. See BUG-3.
- **Result: FAIL** (no priority-based tie-breaking)

#### EC-7: HYBRID path -- HA succeeds but LLM fails
- [x] `callOllama()` catch block returns `'Chat-Anfrage konnte nicht verarbeitet werden.'`
- [x] Response parts combine HA text + LLM fallback text
- [x] HA results are not lost when LLM fails
- **Result: PASS**

---

### Security Audit Results

#### SEC-1: GraphQL Injection in Weaviate Queries
- [ ] **CRITICAL BUG:** The Intent Lookup node constructs a GraphQL query using string interpolation: `const concept = part.replace(/"/g, "'"); const gql = '{ Get { HAIntent( nearText: { concepts: ["${concept}"] } ... } }'`. The only sanitization is replacing double quotes with single quotes. An attacker could inject GraphQL by crafting input containing `'] }) { __typename } } #` or similar payloads with single quotes, backslashes, or closing braces. While the Weaviate GraphQL API may not support destructive mutations via nearText, this is a **GraphQL injection vector** that could be used for information disclosure or denial-of-service. See BUG-7.

#### SEC-2: HA_TOKEN Exposure in Error Messages
- [x] HA_TOKEN is only used in Authorization headers, never logged or returned in responses
- [x] Error messages are generic German text, no token or internal details exposed
- **Result: PASS**

#### SEC-3: No Authentication on Webhook Endpoint
- [ ] The webhook at `POST /webhook/v1/chat/completions` has no authentication. Any caller on the VPN can send requests with arbitrary `user_id` values. The `user_id` defaults to `'andreas'` (admin), so an unauthenticated attacker on the VPN could impersonate the admin user. This is a known Phase 1 limitation (auth comes in Phase 1.5), but it represents a significant risk if VPN access is shared.
- **Result: ACCEPTED RISK** (Phase 1 limitation, documented in CLAUDE.md)

#### SEC-4: User ID Spoofing
- [ ] `user_id` is taken directly from the request body (`body.user_id || 'andreas'`). Any caller can set any `user_id`, including other users' IDs. Messages will be saved to `alice.messages` under the spoofed user_id. This enables cross-user data pollution. Same Phase 1 limitation as SEC-3.
- **Result: ACCEPTED RISK** (Phase 1 limitation)

#### SEC-5: HA Service Call Authorization
- [ ] The workflow does NOT check `alice.permissions_home_assistant` before making HA service calls. Any user (even with spoofed user_id) can control any HA device, including security-critical domains. The `requires_confirmation` check only affects `lock` and `alarm_control_panel` domains, but even those are only confirmation prompts -- not actual authorization checks. The permission infrastructure exists in PROJ-1 but is not wired into the chat handler.
- **Result: NOT IMPLEMENTED** (expected for Phase 1; critical for Phase 3)

#### SEC-6: Rate Limiting
- [ ] No rate limiting on the webhook endpoint. An attacker could flood the endpoint with requests, triggering many parallel Weaviate queries and HA service calls. This could overwhelm Weaviate, PostgreSQL, and Home Assistant.
- **Result: ACCEPTED RISK** (Phase 1 limitation, VPN-only access mitigates)

#### SEC-7: Sensitive Data in DB
- [x] Messages table stores user messages and assistant responses -- appropriate for the memory tier
- [x] `tool_results` JSONB stores intents and HA results -- no secrets stored
- **Result: PASS**

#### SEC-8: HA_TOKEN in Environment Variables
- [x] Follows project convention (env vars for credentials)
- [x] Not hardcoded in the workflow JSON
- **Result: PASS**

---

### Bugs Found

#### BUG-1: Hybrid Executor response builder has fewer action mappings than HA Fast Executor
- **Severity:** Low
- **Status:** ✅ FIXED (2026-02-25) — Both `buildText()` (HA Fast Executor) and `haText()` (Hybrid Executor) now share the same 12 action mappings: turn_on, turn_off, open, close, start, stop, return, lock, unlock, arm, disarm, set_temperature.
- **Priority:** Fix in next sprint (inconsistency, not blocking)

#### BUG-2: HA_FAST confirmation check blocks ALL intents when ANY requires confirmation
- **Severity:** High
- **Status:** ✅ FIXED (2026-02-25) — HA Fast Executor now separates `executableIntents` (non-confirmation) from `needsConfirmation`. Only returns a confirmation prompt if ALL intents require confirmation; otherwise executes the non-confirmation ones and appends a confirmation note for the blocked ones.
- **Priority:** Fix before deployment

#### BUG-3: No priority-based tie-breaking for similar-certainty intents
- **Severity:** Medium
- **Status:** ✅ FIXED (2026-02-25) — Intent Lookup now sorts qualified candidates by certainty descending, then by `priority` descending for tie-breaking (within 0.001 certainty delta). `priority` field is now fetched from Weaviate in the GraphQL query.
- **Priority:** Fix before deployment (spec requirement)

#### BUG-4: tool_calls column never populated in alice.messages
- **Severity:** Medium
- **Status:** ✅ FIXED (2026-02-25) — All three DB Insert nodes (HA Fast, Hybrid, LLM) now include `tool_calls` in the column mapping. HA_FAST and HYBRID paths write the HA API results JSON; LLM path writes `llm_tool_calls` (null for now, ready for future tool-use).
- **Priority:** Fix before deployment (spec requirement)

#### BUG-5: DB write on the HA_FAST critical path may break < 200ms target
- **Severity:** Medium
- **Status:** ✅ FIXED (2026-02-25) — HA_FAST path reordered to fire-and-forget: `Executor → Save → Format → Respond HA Fast → Insert User Msg → DB Insert`. The Respond node now fires before any DB writes, removing PostgreSQL latency from the critical path.
- **Priority:** Fix before deployment (performance requirement)

#### BUG-6: User message not saved to alice.messages
- **Severity:** High
- **Status:** ✅ FIXED (2026-02-25) — Three new Postgres nodes added (`Insert User Msg HA Fast`, `Insert User Msg Hybrid`, `Insert User Msg LLM`), one per path. Each saves `role='user'` with the original user message before the assistant message is written. Both conversation turns (user + assistant) are now fully stored.
- **Priority:** Fix before deployment (breaks memory architecture)

#### BUG-7: GraphQL injection via user input in Weaviate query
- **Severity:** High
- **Status:** ✅ FIXED (2026-02-25) — Intent Lookup now uses `sanitizeForGql()` which escapes backslashes, replaces double quotes with single quotes, strips control characters (`\r\n\t`), and truncates input to 500 characters. This prevents structural GraphQL injection via the concepts array.
- **Priority:** Fix before deployment (injection vulnerability)

#### BUG-8: Hybrid Executor uses hardcoded model name `qwen2.5:14b` instead of env var
- **Severity:** Medium
- **Status:** ✅ FIXED (2026-02-25) — Hybrid Executor `callOllama()` now uses `$env.OLLAMA_MODEL || 'qwen3:14b'` instead of the hardcoded `'qwen2.5:14b'`. Model is now controlled via the `OLLAMA_MODEL` environment variable.
- **Priority:** Fix before deployment (use env var for consistency)

#### BUG-9: Hybrid Executor calls Ollama API directly instead of using n8n AI Agent
- **Severity:** Low
- **Steps to Reproduce:**
  1. In the HYBRID path, `callOllama()` makes a direct HTTP POST to `${OLLAMA_URL}/api/chat`
  2. In the LLM_ONLY path, the AI Agent n8n node is used with proper langchain integration
  3. Expected: Both paths should use the same LLM invocation mechanism for consistent behavior (tool-use support, memory context, etc.)
  4. Actual: HYBRID path bypasses the AI Agent and calls Ollama's raw API directly. This means HYBRID LLM responses have no tool-use capability and only receive the raw message history, missing any AI Agent system prompt, memory injection, or tool definitions.
- **File:** `workflows/core/alice-chat-handler.json`, node `Hybrid Executor`, lines 32-51 of jsCode
- **Note:** This is a design trade-off for simplicity and parallel execution. The direct call allows HA and LLM to run truly in parallel. But it creates a quality difference between HYBRID and LLM_ONLY responses.
- **Priority:** Fix in next sprint (functional difference between paths)

---

### Cross-Browser / Responsive Testing
- **Not applicable:** PROJ-3 is a backend n8n workflow feature with no UI components. The webhook API returns JSON. Frontend chat rendering is handled by existing components (unchanged by this feature).

---

### Regression Testing

#### PROJ-1 (HA Intent Infrastructure) -- Deployed
- [x] No changes to Weaviate schema or PostgreSQL tables
- [x] HAIntent collection is read-only from this workflow's perspective (nearText queries)
- [x] `alice.messages` table schema is unchanged (existing columns reused)
- **Result: No regression**

#### PROJ-2 (hassil-parser) -- Deployed
- [x] No changes to the hassil-parser container or its endpoints
- [x] Workflow reads Weaviate data that was populated by PROJ-2's sync -- no writes to intent tables
- **Result: No regression**

#### Existing LLM_ONLY Chat Path
- [x] LLM_ONLY path connects to the original AI Agent and Ollama Chat Model nodes
- [x] LLM Only Prep reformats the data to match the original webhook body structure
- [ ] BUG (minor): LLM Only Prep wraps messages back into `body.messages`, but the AI Agent node's `text` parameter is set to `={{ $json.body.messages }}`. If the original pre-PROJ-3 workflow passed messages differently, this could be a regression. However, since the AI Agent uses the n8n expression `={{ $json.body.messages }}` and the Prep node provides exactly that structure, it should work.
- **Result: Low regression risk** -- verify during deployment with a live LLM_ONLY request

---

### Performance Analysis (Theoretical)

The HA_FAST critical path has 10 sequential node hops:

```
Webhook (0ms) -> Input Validator (~5ms) -> Empty Input Check (~3ms) ->
Sentence Splitter (~5ms) -> Intent Lookup (30-80ms Weaviate) ->
Path Router (~3ms) -> HA Fast Executor (20-100ms HA) ->
Save Message HA Fast (~5ms) -> DB Insert HA Fast (10-30ms PG) ->
Format Response HA Fast (~5ms) -> Respond HA Fast (~3ms)
```

**Estimated total: ~89-239ms** -- tight for the 200ms target. Moving DB Insert off the critical path would save 10-30ms and make the target much more achievable.

---

### Summary

- **Acceptance Criteria:** 12/16 passed, 2 failed (AC-15: tool_calls missing + user message not saved; AC-12: partial -- HA_FAST confirmation blocking), 2 cannot verify (AC-9, AC-10: require live performance test)
- **Bugs Found:** 9 total (0 critical, 3 high, 3 medium, 3 low)
  - **High (3):** BUG-2 (HA_FAST blocks all intents on confirmation), BUG-6 (user message not saved), BUG-7 (GraphQL injection)
  - **Medium (3):** BUG-3 (no priority tie-breaking), BUG-4 (tool_calls not written), BUG-5 (DB write on critical path), BUG-8 (hardcoded model name)
  - **Low (3):** BUG-1 (inconsistent action mappings), BUG-9 (Hybrid calls Ollama directly)
- **Security:** 1 high-severity injection finding (BUG-7); 3 accepted Phase 1 risks (no auth, user spoofing, no rate limiting); 1 not-implemented (HA permission checks)
- **Production Ready:** NO
- **Blocking Issues:**
  - BUG-2 (HA_FAST confirmation logic blocks non-confirmation intents)
  - BUG-6 (user messages not saved -- breaks memory architecture)
  - BUG-7 (GraphQL injection via user input)
  - BUG-3 (priority tie-breaking not implemented per spec)
  - BUG-4 (tool_calls column never written per spec)
  - BUG-8 (model name mismatch with env var)
- **Recommendation:** Fix BUG-2, BUG-6, BUG-7 (high severity) first. Then fix BUG-3, BUG-4, BUG-5, BUG-8 (medium). After fixes, run `/qa` again with a live environment test to verify performance targets (AC-9, AC-10).

## Deployment
_To be added by /deploy_
