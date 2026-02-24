# PROJ-3: HA-First Chat Handler with Intent Routing

## Status: In Progress
**Created:** 2026-02-23
**Last Updated:** 2026-02-23

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
_To be added by /qa_

## Deployment
_To be added by /deploy_
