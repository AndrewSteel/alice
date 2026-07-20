# PROJ-71: Chat State-Management-Layer

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-20

## Implementation Notes
- All 14 scattered `setMessagesBySession` calls replaced by `dispatch` into a single `useReducer` — 13 action types (`token`, `thinking`, `tool_start`, `tool_end`, `done`, `error`, `abort`, `reload`, `delete_session`, `user_message`, `assistant_placeholder`, `assistant_message`, `error_message`); no parallel state remains.
- `vision_results` deliberately has no reducer case — it never touches `messagesBySession` (pure pass-through to the PROJ-61 flip-card callback).
- Reducer is pure (non-deterministic `newId()`/`Date.now()` moved to dispatch-site payloads), which also fixes a latent React Strict-Mode double-invoke hazard the original scattered-updater code had.
- QA: READY, 0 bugs. 3 Low informational notes (no `never`-exhaustiveness check on the action union; `vision_results` omission documented as correct; purity fix noted as an improvement). No live SSE backend available for QA — recommend a live smoke test pre-deploy (stream, tool call, abort, session-switch mid-stream, mixed-msg_type reload) before/shortly after deploy.

## Dependencies
- None (reiner Frontend-Refactor von `hooks/useChatSessions.ts`, keine Backend-/Protokoll-Änderung).
- Sollte nach PROJ-60 (Theming) und PROJ-62 (i18n) umgesetzt werden, da beide auch `useChatSessions.ts`-Konsumenten (Chat-Renderer) berühren.

## User Stories
- Als Entwickler möchte ich Message-State-Updates an einer zentralen, nachvollziehbaren Stelle vornehmen, statt 13+ verstreute `setMessagesBySession`-Aufrufe mit manuellem Last-Item-Lookup über die Datei verteilt zu pflegen.
- Als Entwickler möchte ich einen neuen SSE-Event-Typ künftig durch einen einzigen neuen Case hinzufügen können, ohne bestehende Update-Logik anderer Event-Typen zu riskieren.
- Als Nutzer soll sich am sichtbaren Chat-Verhalten (Token-Streaming, Tool-Status-Chips, Thinking-Bereiche, Session-Reload-Mapping) durch diesen Refactor nichts ändern.

## Acceptance Criteria
- [ ] Alle Message-State-Updates in `useChatSessions.ts` laufen über einen zentralen Dispatch-Mechanismus (z. B. `useReducer` mit einem Action-Typ je SSE-Event: `token`, `thinking`, `tool_start`, `tool_end`, `vision_results`, `error`, `done`) statt verstreuter `setMessagesBySession(prev => ...)`-Aufrufe.
- [ ] Bestehendes Verhalten bleibt vollständig erhalten: Token-für-Token In-Place-Update der aktiven Assistant-Bubble, Tool-Status-Chips (Start/Ende), einklappbare Thinking-Nachrichten, Session-Reload-Mapping (`user_text/user_stt→user`, `llm_thinking→thinking`, `llm_response→assistant`, `ha_result/tool_result→tool_call`).
- [ ] Kein React-State bleibt außerhalb des zentralen Mechanismus dupliziert (z. B. kein paralleler `messagesBySession`-State neben dem Reducer-State).
- [ ] Testbares Erfolgskriterium für Erweiterbarkeit: Ein neuer, hypothetischer SSE-Event-Typ lässt sich laut Code-Review durch genau einen neuen Reducer-Case + einen neuen Renderer hinzufügen, ohne bestehende Cases anzufassen.
- [ ] Keine sichtbare Verhaltensänderung aus Nutzersicht — reiner interner Refactor.
- [ ] Bestehende manuelle/QA-Testfälle für PROJ-35 (Streaming), PROJ-37 (Tool-Status-Chips), PROJ-51 (Chat-Speicherung/Titel) bleiben ohne Regression bestehen.

## Edge Cases
- Sehr schnelle aufeinanderfolgende `token`-Events (Streaming-Burst): Reducer-Updates dürfen keine Tokens verlieren oder in falscher Reihenfolge anwenden — identisch zum heutigen Verhalten.
- Abbruch eines laufenden Streams (`AbortController`, Stop-Button): der `[Abgebrochen]`-Tag und die Freigabe der Eingabe müssen im neuen Mechanismus weiterhin korrekt gesetzt werden.
- Session-Wechsel während ein Stream noch läuft: State der vorherigen Session darf nicht mit der neu aktivierten Session vermischt werden — bestehendes Verhalten (State ist bereits pro `sessionId` partitioniert) bleibt erhalten.
- Session-Reload mit gemischten `msg_type`-Werten (STT, LLM, HA-Tool-Ergebnisse in beliebiger Reihenfolge): Mapping-Logik bleibt funktional identisch zu heute.

## Technical Requirements (optional)
- Bleibt innerhalb der bestehenden Stack-Konvention "reine React Hooks + Context, kein Redux/Zustand" (frontend-design.md Abschnitt 2) — `useReducer` ist Teil davon, keine neue State-Management-Bibliothek als Abhängigkeit.
- Reiner Frontend-Refactor innerhalb von `hooks/useChatSessions.ts`; keine Änderung an `services/api.ts` (SSE-Parsing) oder dem Backend-Event-Vertrag.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
hooks/useChatSessions.ts
+-- useReducer (neu) — ein Action-Typ je SSE-Event: token, thinking, tool_start, tool_end, vision_results, error, done
    +-- ersetzt die 15 verstreuten setMessagesBySession-Aufrufe
+-- Session-Reload-Mapping (user_text/user_stt→user, llm_thinking→thinking, llm_response→assistant, ha_result/tool_result→tool_call)
    bleibt fachlich identisch, wird aber ebenfalls über den Reducer aufgebaut statt separater State-Manipulation
```

#### B) Data Model

Unverändert — dieselbe Message-Form, dieselbe Partitionierung pro `sessionId`. Diese Spec ändert den State-*Mechanismus*, nicht das Datenmodell.

#### C) Tech Decisions

- **`useReducer` statt neuer State-Bibliothek:** liegt bereits innerhalb der festgelegten Stack-Konvention „reine React Hooks + Context, kein Redux/Zustand" (frontend-design.md §2) — ist das eingebaute React-Primitiv für genau diese Problemform (ein State, viele unterschiedliche Update-Arten), keine neue Abhängigkeit.
- **Ein Reducer-Case je SSE-Event-Typ** ist der Mechanismus, der das Erweiterbarkeits-Akzeptanzkriterium erfüllt (neuer Event-Typ = ein neuer Case, keine bestehenden Cases angefasst) — die heutige implizite Kopplung (manuelle Last-Item-Lookups verstreut über die Datei) ist genau das, was das aktuell unsicher macht.
- **Kein paralleler State:** Der Reducer wird die einzige Quelle der Wahrheit für `messagesBySession` — ein zusätzlicher, dazu paralleler React-State ist explizit ausgeschlossen (genau das Anti-Pattern, das die Akzeptanzkriterien der Spec benennen).
- **Scope-Grenze:** `services/api.ts` (SSE-Parsing) und der Backend-Event-Vertrag bleiben unangetastet — diese Spec ändert nur, wie das Frontend bereits geparste Events konsumiert, kein Protokoll-Wechsel.
- **Verhaltensparität ist das Hauptkriterium:** Token-Streaming-Reihenfolge bei schnellen Bursts, Stream-Abbruch (`[Abgebrochen]`-Tag), Session-Wechsel während laufendem Stream — alles bereits heute über die Partitionierung nach `sessionId` gelöst und muss im Reducer identisch reproduziert werden, nicht neu erfunden.

#### D) Dependencies

Keine neuen Pakete — `useReducer` ist Teil von React.

## QA Test Results

**Tested:** 2026-07-20
**Scope:** Static code review + behavioral-equivalence diff (pre-refactor `HEAD` vs. uncommitted working tree) + production build. No live SSE backend available.
**Tester:** QA Engineer (AI)

### Method

Pure internal refactor of `frontend/src/hooks/useChatSessions.ts`. Bar = zero user-visible behavior change. QA compared the 14 pre-refactor `setMessagesBySession(prev => ...)` call sites against the 13 `useReducer` action cases line-by-line, verified reducer purity, session partitioning, orphan cleanup, and ran `npm run build`.

### Acceptance Criteria Status

#### AC-1: All message-state updates flow through a central dispatch mechanism (one action per SSE event)
- [x] `useReducer(messagesReducer, {})` is the single state holder (line 425).
- [x] All 14 former `setMessagesBySession` call sites replaced by `dispatch(...)`; 13 action cases: `reload` (covers both reload-success and reload-catch), `delete_session`, `user_message`, `assistant_placeholder`, `token`, `thinking`, `tool_start`, `tool_end`, `done`, `error`, `abort`, `assistant_message`, `error_message`.
- [x] No `vision_results` action — verified justified: `vision_results` SSE events (`api.ts:475-479`) call `onVisionResults` → `vision.setResults` in `AppShell.tsx:48`; they never read/write `messagesBySession`. Spec's AC-1 lists `vision_results` only as a "z. B." (e.g.) illustration, so omitting a no-op action is a correct, defensible deviation (see OBS-2).

#### AC-2: Existing behavior fully preserved (token in-place, tool chips, thinking, reload mapping)
- [x] `token` case: identical to original (append to last assistant, else close streaming thinking + push new assistant bubble).
- [x] `thinking` case: identical (convert empty placeholder / append / push new).
- [x] `tool_start` / `tool_end`: identical (close last streaming assistant|thinking; match most-recent running tool_call by name, apply summary).
- [x] `done`: identical (clear streaming on last streaming message).
- [x] `error`: identical, incl. `last` captured **before** the tool_call loop.
- [x] `abort`: identical to original `markStreamAborted`, incl. `last` captured **after** the loop, `[Abgebrochen]` append-vs-push logic, both i18n calls preserved verbatim (`chat.abortedMarker`, `chat.aborted`).
- [x] Reload `msg_type` mapping (`user_text/user_stt→user`, `llm_response→assistant`, `llm_thinking→thinking`, `ha_result/tool_result→tool_call+done`, legacy fallback) unchanged (lines 522-561), fed into the `reload` action.

#### AC-3: No React state duplicated outside the central mechanism
- [x] `grep` confirms the old `useState<Record<string, Message[]>>` is fully removed; only `useReducer` remains. No parallel message state.

#### AC-4: Extensibility — new event = one new case + one renderer, no existing case touched
- [x] Structurally satisfied: `MessagesAction` discriminated union + one `case` per type; adding a variant + case is isolated. See OBS-1 for a safety-net caveat (`default: return state` gives no compile-time exhaustiveness guarantee).

#### AC-5: No visible behavior change from the user's perspective
- [x] Behaviorally equivalent across all 13 actions (see per-action review above). One latent improvement noted (OBS-3), production behavior identical.

#### AC-6: No regression in PROJ-35 (streaming) / PROJ-37 (tool chips) / PROJ-51 (chat storage/titles)
- [x] Static review: streaming, tool-status, and title logic (`beginUserTurn` session-meta update, lines 653-665) unchanged.
- [ ] Cannot be runtime-verified without a live SSE backend — see "Not Runtime-Verified" below. Recommend a pre-deploy smoke test.

### Edge Cases Status

#### EC-1: Rapid consecutive `token` bursts — no lost/reordered tokens
- [x] Dispatches are fired synchronously in SSE-callback order (no `setTimeout`/async wrapping/stale closure); React queues reducer dispatches in call order. Order preserved vs. original setState-updater queue.

#### EC-2: Stream abort (`[Abgebrochen]` tag + input release)
- [x] `stopStreaming`/`selectSession`/`deleteSession` still clear refs/flags synchronously then dispatch `abort`; marker/status logic identical to original.

#### EC-3: Session switch mid-stream — no cross-session state bleed
- [x] Every action reads/writes only `state[action.sessionId]` (or deletes that one key for `delete_session`). Partitioning preserved; no case touches the whole state object incorrectly.

#### EC-4: Reload with mixed `msg_type` order
- [x] `flatMap` mapping unchanged; order preserved through the `reload` action.

### Reducer Purity Check
- [x] No `Date.now()`, `newId()`, `Math.random()`, or `crypto` inside `messagesReducer` (lines 119-393). All non-deterministic values are generated at dispatch sites and passed via payload (`id`, `createdAt`, `statusId`, `statusCreatedAt`). Only side-effect-free `i18n.t(...)` lookups remain in the `abort` case. Reducer is pure and Strict-Mode-double-invoke safe.

### Regression / Orphan Check
- [x] `grep` for `setMessagesBySession` across `src/` → zero remaining references.
- [x] Hook's public return shape unchanged (`messages: Message[]`); only consumer is `AppShell.tsx`, which is unaffected by the internal state-mechanism change. `MessageRenderer` consumes `Message[]` shape — unchanged.

### Build
- [x] `npm run build` passes cleanly (Next.js 15.5.12, compiled + type-checked, 0 errors/warnings).

### Not Runtime-Verified (no live SSE backend)
- Actual token streaming, tool-call start/end chips, thinking collapse, abort marker rendering, and session-reload rendering could not be exercised end-to-end.
- PROJ-35/37/51 manual regression suites not executed.
- **Recommended pre-deploy live smoke test:** (1) send a message and watch token-by-token streaming; (2) trigger a tool call and confirm running→done chip; (3) abort a stream mid-flight and confirm `[Abgebrochen]` marker + input re-enabled; (4) switch sessions mid-stream and confirm no state bleed + prior session gets aborted status; (5) reload a session with mixed `msg_type` values.

### Security Audit Results
- [x] Pure client-side state-management refactor. No new data flow, no auth/authz path, no user-input handling, no new env vars, no network/protocol change (`services/api.ts` and backend event contract untouched).
- **Verdict: PASS** — no security surface introduced or altered.

### Observations (non-blocking)

#### OBS-1: `default: return state` provides no compile-time exhaustiveness guarantee
- **Severity:** Low (informational)
- The reducer ends with `default: return state` instead of a `default: { const _exhaustive: never = action; return state; }` assertion. Dispatch sites are still type-checked (a misspelled `type` errors at the `dispatch(...)` call), so runtime risk is low. However, adding a new variant to `MessagesAction` and forgetting its `case` would compile silently and be swallowed at runtime — weakening the AC-4 "extensibility" safety net. Recommend adding a `never` exhaustiveness check.

#### OBS-2: `vision_results` intentionally not modeled as an action
- **Severity:** Low (informational / design deviation, justified)
- AC-1 and Tech Design enumerate `vision_results` among example action types. It is correctly omitted because that event never mutates `messagesBySession`. Documented here for traceability; not a defect.

#### OBS-3: Latent Strict-Mode fix (behavior improvement, not a regression)
- **Severity:** Low (informational)
- Moving `newId()`/`Date.now()` out of the setState updaters into dispatch payloads eliminates a latent React-Strict-Mode double-invoke hazard the original code had (IDs/timestamps could differ per invoke). Production behavior is identical; dev behavior is strictly improved.

### Bugs Found
None. No Critical, High, Medium, or Low functional bugs. Three Low informational observations above.

### Summary
- **Acceptance Criteria:** 6/6 passed (AC-6 static-only; live regression pending smoke test).
- **Edge Cases:** 4/4 passed (static review).
- **Bugs Found:** 0 (0 critical, 0 high, 0 medium, 0 low). 3 Low informational observations.
- **Security:** PASS (no security surface).
- **Build:** PASS.
- **Production Ready:** YES — conditional on a pre-deploy live SSE smoke test (below) to close the no-backend gap for the streaming/tool/abort/reload paths.
- **Recommendation:** READY. Merge after a manual live-session smoke test covering the 5 scenarios listed under "Not Runtime-Verified". Optionally address OBS-1 to harden the extensibility guarantee.

## Deployment
_To be added by /deploy_
