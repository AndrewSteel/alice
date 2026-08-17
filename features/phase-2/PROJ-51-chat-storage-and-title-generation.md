# PROJ-51: Chat-Protokoll-Speicherung & Titelgenerierung

## Status: Deployed
**Created:** 2026-06-17
**Last Updated:** 2026-06-17

## Dependencies
- Requires: PROJ-35 (Chat Frontend Redesign) — Message-Typen `thinking`, `tool_call` im Frontend definiert
- Requires: PROJ-38 (Sidebar Context-Menu) — Session-Rename-Flow bleibt erhalten
- Requires: PROJ-40 (Speech Gateway) — ESPHome-Sessions gehen durch denselben Pipeline-Stack
- Requires: PROJ-41 (WebApp Voice Interface) — WebApp-MIC-Quelle muss erkannt werden
- Enables: PROJ-52 (Admin-Chatarchiv) — setzt auf erweitertes Datenmodell auf

---

## Kontext & Motivation

Seit PROJ-35 und PROJ-38 bestehen zwei ungeklärte Regressions:

1. **"Unbenannter Chat"** — Die Sidebar zeigt meistens keinen Titel, weil `alice.sessions.title` nach der Session-Erstellung nie befüllt wird. Es fehlt eine automatische Titelgenerierung.
2. **Thinking-Nachrichten fehlen beim Session-Restore** — Beim Öffnen einer gespeicherten Session aus der Sidebar fehlen die `thinking`-Nachrichten, weil sie bisher weder gespeichert noch beim Nachladen aus der DB zurückgeliefert werden.

Zusätzlich fehlt ein vollständiges Protokoll aller Chats. Aktuell werden pro Message nur `user`- und `assistant`-Rollen gespeichert. STT-Transkripte, LLM-Thinking-Tokens, HA-Ergebnisse und die Quell-Information (WebApp CC / WebApp MIC / ESPHome) gehen verloren.

Diese Spec definiert:
- Erweitertes Nachrichtenmodell mit Quell- und Typinformation
- Retention-Logik: 30 Tage für alle Sessions, dauerhaft für LLM-Sessions
- Automatische Titelgenerierung nach der ersten vollständigen LLM-Antwort
- Session-Restore mit allen Nachrichtentypen inkl. Thinking

---

## User Stories

1. **Als Nutzer** möchte ich, dass in meiner Sidebar ein aussagekräftiger Titel für jeden Chat erscheint (nicht "Unbenannter Chat"), damit ich frühere Gespräche auf Anhieb wiederfinde.
2. **Als Nutzer** möchte ich, dass beim Öffnen einer früheren Session alle Thinking-Nachrichten des LLMs wieder angezeigt werden, damit ich den vollständigen Denkprozess nachvollziehen kann.
3. **Als Nutzer** möchte ich, dass LLM-Chats dauerhaft in meiner Chat-Sidebar gespeichert werden (bis ich sie selbst lösche), damit ich auch ältere Gespräche wiederfinde.
4. **Als Nutzer** möchte ich, dass reine Smarthome-Befehle (HA-only) NICHT in meiner Chat-Sidebar erscheinen, damit die History übersichtlich bleibt.
5. **Als Nutzer (alle Kanäle)** möchte ich, dass alle meine Interaktionen — egal ob per Sprache über ESPHome, per Mikrofon in der WebApp oder per Tastatur — mindestens 30 Tage protokolliert werden, damit ich im Nachhinein nachvollziehen kann, was gesagt wurde.
6. **Als Nutzer** möchte ich, dass alle Nachrichtentypen eines Chats gespeichert werden (STT-Transkript, LLM-Thinking, LLM-Antwort, HA-Ergebnis), auch wenn nicht alle im WebApp dargestellt werden.

---

## Acceptance Criteria

### A) Session-Klassifizierung & Retention

- [x] **AC-A1**: Jede Session hat einen Typ: `llm` oder `ha_only`. Eine Session ist `llm`, wenn mindestens eine vollständige LLM-Antwort (nicht über den HA-Fast-Path) erzeugt wurde.
- [x] **AC-A2**: `ha_only`-Sessions erhalten beim Erstellen automatisch eine Ablaufzeit von 30 Tagen ab `started_at`. Sie erscheinen NICHT in der Sidebar-History des Nutzers.
- [x] **AC-A3**: `llm`-Sessions haben kein Ablaufdatum und erscheinen in der Sidebar-History.
- [x] **AC-A4**: Wenn in einer `ha_only`-Session erstmals eine LLM-Anfrage beantwortet wird, wird die Session zu `llm` befördert: Ablaufdatum wird entfernt, Session erscheint in der Sidebar.
- [x] **AC-A5**: Ein Cleanup-Mechanismus löscht abgelaufene `ha_only`-Sessions (und deren Nachrichten via CASCADE) automatisch. Es entstehen keine verwaisten Datensätze.
- [x] **AC-A6**: Der Cleanup gilt für alle Quellen (ESPHome, WebApp CC, WebApp MIC).

### B) Erweitertes Nachrichtenmodell

- [x] **AC-B1**: Jede Nachricht hat neben der bestehenden `role`-Spalte (für den LLM-Kontext) eine neue Typinformation, die den Anzeigetyp beschreibt. Mindestens folgende Typen werden unterschieden: `user_text`, `user_stt`, `llm_thinking`, `llm_response`, `ha_result`, `tool_result`.
- [x] **AC-B2**: Spracheingaben (ESPHome STT, WebApp MIC) werden als `user_stt` gespeichert. Tastatureingaben (WebApp CC) werden als `user_text` gespeichert.
- [x] **AC-B3**: LLM-Thinking-Tokens werden vollständig als `llm_thinking`-Nachricht gespeichert, sobald das LLM eine `done`-Event schickt (gesammelt aus dem Stream). Auch wenn der Nutzer den Stream abbricht, werden die bis dahin empfangenen Thinking-Tokens gespeichert.
- [x] **AC-B4**: HA-Ergebnisse (welche Intents ausgeführt wurden, Erfolg/Misserfolg per Gerät) werden als `ha_result`-Nachricht gespeichert.
- [x] **AC-B5**: Die Quelle der Session wird gespeichert: `webapp_cc` (Tastatur), `webapp_mic` (Mikrofon), `esphome` (Wyoming-Satellite). Die Quell-Information gilt pro Session (nicht pro Nachricht).

### C) Titelgenerierung

- [x] **AC-C1**: Nach Abschluss der **ersten vollständigen LLM-Antwort** (SSE `done`-Event, path ≠ HA_FAST) wird asynchron ein Titel für die Session generiert.
- [x] **AC-C2**: Der generierte Titel ist ein kurzes, deutschsprachiges Label (max. 60 Zeichen), das den Kern des ersten User→LLM-Austauschs zusammenfasst. Er wird per Ollama-Aufruf generiert (separater, kurzer Prompt nach Streaming-Ende).
- [x] **AC-C3**: Der Titel wird in `alice.sessions.title` gespeichert. Die Sidebar aktualisiert sich beim nächsten Laden oder per optimistischem Update.
- [x] **AC-C4**: Hat der Nutzer einen Titel manuell gesetzt (PROJ-12), wird er durch die Auto-Generierung **nicht** überschrieben (Bedingung: `title IS NULL`).
- [x] **AC-C5**: Bis der Titel generiert ist, zeigt die Sidebar "Neuer Chat" (nicht "Unbenannter Chat").
- [x] **AC-C6**: Schlägt die Titelgenerierung fehl (Ollama nicht erreichbar, Timeout), bleibt der Titel `NULL`. Der Nutzer sieht "Neuer Chat" und kann den Titel manuell setzen. Kein Fehler wird an den Nutzer gemeldet.

### D) Session-Restore mit Thinking-Nachrichten

- [x] **AC-D1**: Beim Laden einer gespeicherten Session aus der Sidebar (`GET /api/webhook/alice/sessions/messages?session_id=...`) werden alle gespeicherten Nachrichtentypen zurückgeliefert — nicht nur `user` und `assistant`.
- [x] **AC-D2**: Das Frontend bildet die gespeicherten Nachrichtentypen korrekt auf die `Message`-Rollen ab: `llm_thinking` → `thinking`, `ha_result` → `tool_call`, `tool_result` → `tool_call`, `user_stt`/`user_text` → `user`, `llm_response` → `assistant`.
- [x] **AC-D3**: Thinking-Nachrichten werden beim Session-Restore im `ThinkingMessage`-Renderer dargestellt (wie bei Live-Streaming).
- [x] **AC-D4**: HA-Ergebnisse werden beim Session-Restore als eigene Nachrichtenzeile dargestellt (differenzierbar von LLM-Antworten).

---

## Edge Cases

- **Titel-Generierung dauert länger als gewünscht**: Asynchron nach `done`; der Nutzer kann weiter chatten. Sidebar aktualisiert sich beim nächsten Load.
- **Session wechselt von HA-only zu LLM**: Alle bisherigen HA-Nachrichten bleiben erhalten; nur Session-Typ und Ablaufdatum ändern sich.
- **Nutzer löscht Session manuell (PROJ-14)**: Session + alle Nachrichten sofort gelöscht (ON DELETE CASCADE). Unabhängig vom Cleanup-Mechanismus.
- **Sehr lange Thinking-Tokens (> 10.000 Zeichen)**: Vollständig gespeichert — TEXT-Spalte in PostgreSQL hat kein Limit.
- **Nutzer bricht Stream ab**: Bis zu diesem Zeitpunkt gesammelte Thinking-Tokens werden im `finally`-Block gespeichert.
- **ESPHome sendet nur transkribierten Text, kein Audio**: Quelle `esphome` + Typ `user_stt` wird durch die Session-Quelle erkannt, nicht durch die Payload.
- **Gleichzeitige Sessions desselben Nutzers**: Jede Session ist unabhängig; keine Konflikte.
- **Cleanup-Job läuft, während Nutzer Session aktiv nutzt**: Cleanup prüft `expires_at`; eine aktive Session (z.B. durch aktuelles `last_activity`) mit korrekt gesetztem `expires_at` wird gelöscht wenn abgelaufen. Kein Schutz für aktive Sessions nötig — wenn eine Session 30 Tage alt ist, war sie inaktiv.

---

## Technical Requirements

- **Performance**: Titelgenerierung darf die Antwort-Latenz für den Nutzer nicht erhöhen — muss asynchron im Hintergrund laufen.
- **Datenbank**: Neue Spalten in `alice.sessions` und `alice.messages`; bestehende Daten bleiben erhalten (keine Datenmigration der alten Nachrichten nötig).
- **Cleanup**: Täglicher Cron-Job oder n8n Schedule-Trigger der ablaufenden Sessions bereinigt.
- **Rückwärtskompatibilität**: `alice-session-api` (n8n) muss die erweiterten Nachrichtentypen im API-Response mitliefern; das Frontend muss unbekannte Typen ignorieren (kein Crash).
- **Quellen-Erkennung**: Die Quelle (webapp_cc / webapp_mic / esphome) muss im Request an `alice-chat-stream` mitgegeben werden.

---

## Tech Design (Solution Architect)

### Overview

This feature touches three layers: **database schema** (two tables), **alice-chat-stream** (Python), and **alice-session-api + new cleanup workflow** (n8n). The frontend changes are minimal — source detection and message-type mapping on restore.

---

### A) Component Structure

```
alice-chat-stream (Python/FastAPI)
+-- ChatRequest              ← new optional field: source (webapp_cc | webapp_mic | esphome)
+-- memory.py
|   +-- ensure_session       ← sets session_type, source, expires_at on INSERT
|   +-- promote_to_llm       ← removes expires_at, sets session_type='llm'
|   +-- insert_user_message  ← now writes msg_type (user_text | user_stt)
|   +-- insert_llm_thinking  ← NEW: saves accumulated thinking tokens
|   +-- insert_llm_response  ← replaces insert_assistant_message for LLM path
|   +-- insert_ha_result     ← NEW: saves HA fast-path result
|   +-- generate_title_async ← NEW: background Ollama call → UPDATE sessions.title
+-- streaming.py
    +-- side dict             ← adds thinking_text accumulation (alongside final_text)

alice-session-api (n8n workflow — updated)
+-- GET /alice/sessions       ← adds filter: session_type='llm' OR session_type IS NULL
+-- GET /alice/sessions/messages ← returns all msg_types with frontend mapping

alice-session-cleanup (n8n workflow — NEW)
+-- Schedule Trigger (daily 03:00)
+-- PostgreSQL: DELETE expired ha_only sessions

Frontend (React)
+-- services/api.js           ← streamChat() gains source parameter
+-- useChatSessions.ts
|   +-- sendMessage           ← passes source (keyboard=webapp_cc, mic=webapp_mic)
|   +-- loadSessionMessages   ← maps msg_type → Message type on restore
+-- ChatListItem.tsx          ← "Neuer Chat" fallback for null title
```

---

### B) Data Model

**alice.sessions — 3 new columns (additive, backward compatible):**

```
session_type  TEXT   — 'llm' (default, permanent) or 'ha_only' (auto-deleted after 30 days)
expires_at    TIMESTAMP — NULL for llm sessions; set to started_at + 30 days for ha_only
source        TEXT   — 'webapp_cc', 'webapp_mic', or 'esphome' (set on INSERT, never changed)
```

The existing `title`, `started_at`, `last_activity`, `is_active` columns remain unchanged.

**alice.messages — 1 new column (additive, nullable for backward compat):**

```
msg_type  TEXT — one of: user_text, user_stt, llm_thinking, llm_response, ha_result, tool_result
                 NULL for messages written before this feature was deployed
```

The existing `role` column (user / assistant / system / tool) is retained — it drives the LLM context window and must not change.

**Mapping from msg_type → frontend Message type (for session restore):**

| msg_type             | Frontend Message role |
|----------------------|-----------------------|
| user_text, user_stt  | user                  |
| llm_response         | assistant             |
| llm_thinking         | thinking              |
| ha_result            | tool_call             |
| tool_result          | tool_call             |
| NULL (legacy)        | use existing `role`   |

---

### C) Tech Decisions

**Session classification is set at INSERT time, not per-message.** Every new session starts as `ha_only` with `expires_at = NOW() + 30 days`. The moment the first LLM response is saved, `promote_to_llm()` runs inside the same DB transaction: sets `session_type='llm'` and clears `expires_at`. This avoids any ambiguity and keeps the classification logic in one place (memory.py).

**Thinking tokens are accumulated in `streaming.py`'s `side` dict**, the same mechanism already used for `final_text` and `tool_calls`. The `side["thinking_text"]` string is passed to `insert_llm_thinking()` in the `finally` block. If the user disconnects mid-stream, `finally` still runs and saves whatever thinking tokens were received (AC-B3).

**Title generation runs as a background asyncio task** — it does not block the SSE stream or the `finally` block. The task fires only when `COUNT(msg_type='llm_response') = 1` for the session, meaning this is the first LLM response. It calls Ollama with a short separate prompt (not the main model loop), updates `sessions.title WHERE title IS NULL` (idempotent), and exits silently on failure (AC-C6). The frontend picks up the new title on the next `fetchSessions()` call — no polling needed.

**Sidebar shows "Neuer Chat"** for sessions with `title = NULL`. This is a one-line change in `ChatListItem.tsx`. The existing "Unbenannter Chat" fallback is replaced.

**Source detection in the frontend:** the `InputArea` already knows whether the user typed (keyboard) or spoke (microphone via `VoiceOverlay`). The `sendMessage` call in `useChatSessions.ts` is extended with a `source` parameter. The speech-gateway (PROJ-40/41) already forwards requests to `alice-chat-stream` — it will pass `source: "esphome"` in its own request body.

**The cleanup workflow is a new, simple n8n workflow** (`alice-session-cleanup`) with two nodes: a Schedule Trigger (daily at 03:00) and a single PostgreSQL DELETE. ON DELETE CASCADE in the schema handles the messages automatically.

---

### D) Dependencies (no new packages)

No new npm packages or Python libraries are needed. The feature uses:
- `asyncpg` (already in alice-chat-stream) — new DB queries
- `httpx` (already in alice-chat-stream) — Ollama call for title generation
- `asyncio.create_task` (stdlib) — background title generation

---

### E) Workflow Architecture

**alice-chat-stream changes (per request):**
- Trigger: SSE `POST /stream/chat` (unchanged URL)
- Input: `{ session_id, content, source? }` — source is new
- On INSERT session: `session_type='ha_only'`, `expires_at=+30d`, `source=<input>`
- On LLM `done`: promote session to `llm`, save thinking + response, fire background title task
- On HA_FAST `done`: save `ha_result` message, session stays `ha_only`
- Optional SSE: no new event types added (title delivered via next session list fetch)

**alice-session-cleanup (new n8n workflow):**
- Trigger: Schedule, daily at 03:00
- Processing: single DELETE query for expired sessions
- Output: none (logged in n8n execution history)

## Implementation Notes (Backend — 2026-06-17)

Backend changes implemented (frontend changes pending — items D2/D3/D4 and source detection in `useChatSessions.ts`/`ChatListItem.tsx` are not part of this backend pass):

- **DB schema**: `sql/migrations/014-chat-storage.sql` adds `session_type`, `expires_at`, `source` to `alice.sessions` and `msg_type` to `alice.messages`, plus cleanup/type indexes. The same columns were added inline to `sql/init-schema.sql` (the consolidated source of truth) so a fresh DB matches the migration.
- **alice-chat-stream/memory.py**:
  - `ensure_session(session_id, user_id, source)` now inserts new sessions as `ha_only` with `expires_at = NOW() + 30 days` and records `source`.
  - New `promote_to_llm()` clears expiry and sets `session_type='llm'` (only from `ha_only`).
  - `insert_user_message()` gains `msg_type` (`user_text`/`user_stt`).
  - New `insert_llm_thinking()` (role=`system`, kept out of LLM context), `insert_llm_response()` (renamed from `insert_assistant_message`, msg_type=`llm_response`), `insert_ha_result()` (msg_type=`ha_result`, session stays `ha_only`), and `count_llm_responses()`.
  - New `generate_title_async()` — background Ollama `/api/generate` call, writes `title WHERE title IS NULL`, fails silently.
- **alice-chat-stream/streaming.py**: accumulates thinking tokens into `side["thinking_text"]`.
- **alice-chat-stream/main.py**: `ChatRequest.source` validated; user-message msg_type derived from source; finally-block branches on `path_label` (HA_FAST → `insert_ha_result`; else promote + thinking + response + fire title task on first LLM response). Added admin endpoints for PROJ-52: `GET /admin/sessions`, `GET /admin/sessions/{id}`, `DELETE /admin/sessions/{id}` (admin-only via `_require_admin`). `side` hoisted to top of `event_generator` to stay defined in `finally`.
- **alice-speech-gateway/chat_client.py**: forwards `source: "esphome"`.
- **n8n alice-session-api**: session list filtered to `session_type='llm' OR session_type IS NULL`; messages query returns `msg_type`.
- **n8n alice-session-cleanup** (new): daily 03:00 schedule deletes expired `ha_only` sessions (CASCADE removes messages).

Covered ACs (backend): A1–A6, B1–B5, C1–C6, D1. Pending (frontend): D2, D3, D4 and source detection in WebApp.

Deploy actions required: apply `sql/migrations/014-chat-storage.sql`, rebuild/redeploy `alice-chat-stream` and `alice-speech-gateway`, deploy n8n-workflow `alice-session-api` and `alice-session-cleanup`.

## QA Test Results

**Tested:** 2026-06-17
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-A: Session-Klassifizierung & Retention
- [x] AC-A1: Session starts as `ha_only`; promoted to `llm` after first complete LLM response via `promote_to_llm()` in finally block
- [x] AC-A2: `ha_only` sessions get `expires_at = NOW() + 30 days` on INSERT; excluded from user sidebar (n8n query filter: `session_type='llm' OR session_type IS NULL`)
- [x] AC-A3: `llm` sessions have `expires_at = NULL` after `promote_to_llm()`
- [x] AC-A4: `promote_to_llm()` called in `finally` block when `path_label != "HA_FAST"`; HA path leaves session as `ha_only`
- [x] AC-A5: `alice-session-cleanup` n8n workflow (daily 03:00) deletes expired `ha_only` sessions; messages removed via CASCADE
- [x] AC-A6: Cleanup applies to all sources (no source filter in cleanup query)

#### AC-B: Erweitertes Nachrichtenmodell
- [x] AC-B1: `msg_type` column with CHECK constraint on all 6 types in SQL migration + init-schema
- [x] AC-B2: `msg_type = "user_stt"` when `source in ("webapp_mic", "esphome")`, else `"user_text"`
- [x] AC-B3: `thinking_accumulator` in streaming.py collects all thinking chunks across all rounds; `insert_llm_thinking()` called in `finally` block (runs even on disconnect or abort)
- [x] AC-B4: `insert_ha_result()` called when `path_label == "HA_FAST"` in finally block
- [x] AC-B5: `source` column stored per session on INSERT; speech-gateway passes `"esphome"`; InputArea tracks voice vs keyboard and passes `"webapp_cc"` / `"webapp_mic"`

#### AC-C: Titelgenerierung
- [x] AC-C1: `asyncio.create_task(generate_title_async(...))` fires after first LLM response when `count_llm_responses(session_id) == 1`; non-blocking
- [x] AC-C2: Short German title (max 60 chars) via Ollama `/api/generate` with `think: False`; truncated at 60 chars
- [x] AC-C3: `UPDATE sessions SET title = $1 WHERE session_id = $2::uuid AND title IS NULL`
- [x] AC-C4: `WHERE title IS NULL` prevents overwriting manually set titles
- [x] AC-C5: `s.title || "Neuer Chat"` fallback in useChatSessions.ts (corrected from "Unbenannter Chat")
- [x] AC-C6: All exceptions in `generate_title_async` caught silently; no user-facing error; title stays NULL

#### AC-D: Session-Restore mit Thinking-Nachrichten
- [x] AC-D1: n8n messages query now returns `msg_type`; `MessageResponse` TypeScript type includes `msg_type?`
- [x] AC-D2: useChatSessions.ts maps `msg_type` → Message role: `user_text/user_stt→user`, `llm_response→assistant`, `llm_thinking→thinking`, `ha_result/tool_result→tool_call`; legacy NULL→falls back to `role` column
- [x] AC-D3: `llm_thinking` → role `thinking` → `ThinkingMessage` renderer; stored as `role='system'` in DB so excluded from LLM context window in `load_working_memory`
- [x] AC-D4: `ha_result` → role `tool_call` with `toolStatus: "done"` → `ToolCallMessage` renderer (shows HA response text with checkmark icon)

### Edge Cases Status
- [x] Titelgenerierung dauert länger als gewünscht: non-blocking `asyncio.create_task`, user can keep chatting
- [x] Session HA→LLM: `promote_to_llm` only updates `ha_only` sessions; all HA messages preserved
- [x] Nutzer löscht Session: ON DELETE CASCADE; independent of cleanup job
- [x] Sehr lange Thinking-Tokens: TEXT column (no limit); accumulator joined at end of all rounds
- [x] Nutzer bricht Stream ab: `finally` always runs in async generator; partial thinking_text saved
- [x] ESPHome: speech-gateway always sends `source: "esphome"` in request body
- [x] Gleichzeitige Sessions: fully independent by session_id UUID

### Security Audit Results
- [x] Authentication: All alice-chat-stream endpoints require valid JWT via `verify_jwt` dependency
- [x] Admin access: `_require_admin` checks `jwt_payload["role"] == "admin"` server-side; returns HTTP 403 for non-admins
- [x] Input validation: `source` validated by Pydantic (3 allowed values); session_id validated as UUID in both user and admin endpoints
- [x] SQL injection: All Python DB queries use asyncpg parameterized queries (`$1`, `$2`); no string formatting in SQL
- [x] Source integrity: `user_id` always from verified JWT; `source` is metadata only, not security-sensitive
- [x] No secrets in logs: title generation calls local Ollama; no external API keys involved

### Bugs Found

None.

### Summary
- **Acceptance Criteria:** 20/20 passed
- **Bugs Found:** 0
- **Security:** Pass
- **Production Ready:** YES
- **Recommendation:** Deploy after applying SQL migration 014 and redeploying alice-chat-stream, alice-speech-gateway, and n8n workflows (alice-session-api, alice-session-cleanup)

## Deployment

**Deployed:** 2026-06-17

### Artifacts deployed
- `sql/migrations/014-chat-storage.sql` — applied to production DB
- `sql/migrations/015-source-esphome-device.sql` — applied post-deployment (see Bugs below)
- `alice-chat-stream` container rebuilt (memory.py, main.py, streaming.py)
- `alice-speech-gateway` container rebuilt (chat_client.py, pipeline.py, wyoming_transport.py)
- n8n workflow `alice-session-api` redeployed (session_type filter + msg_type in messages response)
- n8n workflow `alice-session-cleanup` deployed (new — daily cleanup at 03:00)
- Frontend redeployed (useChatSessions.ts, services/api.ts, SettingsPage.tsx)

### Post-deployment bugs found and fixed

**Bug 1 — message_count atomicity:** INSERT into `alice.messages` and UPDATE of `message_count` in `alice.sessions` were two separate asyncpg calls. A connection interruption between them left the message stored but the count un-incremented. Fixed by combining both into a single PostgreSQL CTE statement in `insert_user_message`, `insert_ha_result`, and `insert_llm_response`.

**Bug 2 — session_type='llm' with no LLM response:** `promote_to_llm()` was called before `insert_llm_response()` in the finally block. If the LLM was cancelled or timed out, the session was permanently marked as `llm` with no stored response, causing it to appear in the sidebar incorrectly. Fixed by merging the promotion into `insert_llm_response` as part of the same CTE — session only becomes `llm` when a response is actually persisted. The standalone `promote_to_llm()` call in `main.py` was removed.

**Bug 3 — sessions.source CHECK constraint too strict:** The constraint `CHECK (source IN ('webapp_cc','webapp_mic','esphome'))` rejected device-specific sources like `esphome:Büro`. Fixed via migration 015 which replaces the constraint with one that additionally allows `LIKE 'esphome:%'`.

**Enhancement — ESPHome device distinction:** The `source` field now includes the room name from `device-mapping.yaml` (e.g., `esphome:Büro`, `esphome:Küche`) so sessions from different hardware devices can be distinguished in the archive. Changed files: `chat_client.py` (new `device_id` param), `pipeline.py` (threads `device_id`), `wyoming_transport.py` (passes `device.room`), `main.py` (validator extended for `esphome:*`).
