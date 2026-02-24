# PROJ-3: HA-First Chat Handler with Intent Routing

## Status: Planned
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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
