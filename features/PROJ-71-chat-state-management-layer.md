# PROJ-71: Chat State-Management-Layer

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
