# PROJ-52: Admin-Chatarchiv

## Status: Deployed
**Created:** 2026-06-17
**Last Updated:** 2026-06-17

## Dependencies
- Requires: PROJ-51 (Chat-Protokoll-Speicherung & Titelgenerierung) — erweitertes Datenmodell mit Nachrichtentypen und Session-Klassifizierung
- Requires: PROJ-26/27 (User Management / Settings) — Settings-Tab als Einstiegspunkt

---

## Kontext & Motivation

Als Admin möchte Andreas alle Chats aller Nutzer der letzten 30 Tage einsehen und bei Bedarf löschen können. Dies umfasst auch Chats, die nicht in der Sidebar der Nutzer erscheinen (HA-only-Sessions), sowie Chats aus allen Kanälen (ESPHome, WebApp CC/MIC).

Das Admin-Chatarchiv ist ein neuer Tab im bestehenden Einstellungen-Bereich und wird ausschließlich für Admin-Nutzer angezeigt.

---

## User Stories

1. **Als Admin** möchte ich unter Einstellungen eine Liste aller Chats aller Nutzer der letzten 30 Tage sehen, damit ich einen vollständigen Überblick über die Systemnutzung habe.
2. **Als Admin** möchte ich einen Chat aus der Liste auswählen und den vollständigen Inhalt sehen — differenziert nach STT-Transkript, LLM-Thinking, LLM-Antwort und HA-Ergebnis — damit ich die KI-Interaktionen im Detail nachvollziehen kann.
3. **Als Admin** möchte ich einen Chat aus der Liste oder der Detail-Ansicht löschen, damit ich fehlerhafte oder unerwünschte Einträge entfernen kann.
4. **Als Nicht-Admin-Nutzer** möchte ich keinen Zugriff auf das Chatarchiv anderer Nutzer haben, damit die Privatsphäre gewahrt ist.

---

## Acceptance Criteria

### A) Zugang & Navigation

- [x] **AC-A1**: Im Einstellungen-Bereich gibt es einen neuen Tab "Chatarchiv" (oder "Alle Chats"), der ausschließlich für Nutzer mit `role = 'admin'` sichtbar ist.
- [x] **AC-A2**: Nicht-Admin-Nutzer sehen den Tab nicht und erhalten bei direktem URL-Zugriff einen 403-Fehler (Zugriff verweigert).
- [x] **AC-A3**: Der Tab ist responsiv (Mobile 375px, Tablet 768px, Desktop 1440px).

### B) Listenansicht

- [x] **AC-B1**: Die Liste zeigt alle Sessions der letzten 30 Tage, aller Nutzer, geordnet nach `started_at` absteigend (neueste zuerst).
- [x] **AC-B2**: Jede Zeile in der Liste zeigt: Benutzername (Display Name), Startdatum & -uhrzeit, Session-Typ (LLM / HA-only), Titel (falls vorhanden, sonst "—"), Anzahl Nachrichten, Quelle (WebApp CC / WebApp MIC / ESPHome).
- [x] **AC-B3**: LLM-Sessions, die dauerhaft gespeichert sind und älter als 30 Tage sind, erscheinen NICHT in dieser Liste (nur die letzten 30 Tage, unabhängig vom Retention-Typ).
- [x] **AC-B4**: Die Liste unterstützt Paginierung (20 Einträge pro Seite) oder Infinite-Scroll.
- [x] **AC-B5**: Die Liste hat einen Ladeindikator, solange die Daten geladen werden.
- [x] **AC-B6**: Ein Mülleimer-Icon in jeder Zeile öffnet einen Bestätigungsdialog ("Chat wirklich löschen?") und löscht nach Bestätigung die Session inklusive aller Nachrichten.

### C) Detail-Ansicht

- [x] **AC-C1**: Ein Klick auf eine Session öffnet die Detail-Ansicht mit dem vollständigen Chat-Inhalt (alle gespeicherten Nachrichten in chronologischer Reihenfolge).
- [x] **AC-C2**: Die Darstellung differenziert visuell zwischen den Nachrichtentypen (gemäß PROJ-51-Datenbankmodell):
  - `user_stt` / `user_text` → Nutzereingabe-Bubble (wie im WebApp-Chat)
  - `llm_thinking` → Thinking-Darstellung (dezent, grau, wie ThinkingMessage)
  - `llm_response` → Assistenten-Antwort (wie AssistantMessage)
  - `ha_result` → HA-Ergebnis mit Kennzeichnung
  - `tool_result` → Tool-Ergebnis mit Kennzeichnung
- [x] **AC-C3**: Die Detail-Ansicht zeigt einen Metadaten-Header: Benutzername, Session-ID, Startzeit, Quelle.
- [x] **AC-C4**: Die Detail-Ansicht hat einen Zurück-Button zur Listenansicht.
- [x] **AC-C5**: Löschen ist auch aus der Detail-Ansicht möglich (Mülleimer-Button mit Bestätigungsdialog). Nach dem Löschen kehrt die Ansicht zur Liste zurück.
- [x] **AC-C6**: Wenn eine Session keine Nachrichten hat, zeigt die Detail-Ansicht "Keine Nachrichten gespeichert."

---

## Edge Cases

- **Admin löscht LLM-Session, die in der Sidebar des Nutzers erscheint**: Session verschwindet auch aus der Sidebar des Nutzers (Konsistenz via CASCADE-Delete).
- **Session wurde zwischen Laden der Liste und Klick auf Detail gelöscht** (z.B. durch Cleanup-Job): Detail-Ansicht zeigt "Session nicht mehr vorhanden" und kehrt zur Liste zurück.
- **Zwei Admins löschen gleichzeitig dieselbe Session**: Zweiter Löschversuch gibt einen 404-Fehler — Fehlermeldung anzeigen, Liste neu laden.
- **Sehr viele Sessions** (> 500): Paginierung verhindert Performance-Probleme; kein Volltext-Load auf einmal.
- **Session hat nur Thinking-Tokens und keine finale Antwort** (abgebrochener Stream): Wird trotzdem vollständig angezeigt.
- **Benutzername wurde nach dem Chat geändert**: Anzeige des aktuellen Display Name aus `alice.users`.
- **Nutzer wurde gelöscht**: Sessions mit verwaisten `user_id`s werden durch CASCADE gelöscht — erscheinen nicht mehr in der Liste.

---

## Technical Requirements

- **Security**: Alle Admin-API-Endpunkte müssen serverseitig die Admin-Rolle prüfen (JWT + DB-Abgleich). Kein reines Client-Side-Hiding.
- **Performance**: Listenabfrage mit Paginierung < 500ms. Detail-Abfrage < 300ms.
- **API**: Neuer Admin-Endpunkt für Chatliste und Session-Detail (n8n oder alice-chat-stream, tbd in /architecture).
- **Frontend**: Neuer Tab in `components/Settings/SettingsPage.tsx`. Kein eigener Router-Eintrag — Tabs bleiben im Settings-Bereich.

---

## Tech Design (Solution Architect)

### Overview

Primarily a **frontend feature** with **3 new API endpoints** added to `alice-chat-stream` (Python). No n8n workflow needed — the PROJ-51 data model is read directly via the existing Python service, which already handles JWT auth and DB access.

---

### A) Component Structure

```
SettingsPage.tsx (existing — add one TabsTrigger + one TabsContent)
└── ChatarchivSection (new)
    ├── [List View — default]
    │   ├── SessionsTable (shadcn Table — 20 rows/page)
    │   │   └── Row: username · started_at · type badge · title · msg_count · source badge · delete icon
    │   ├── Pagination (shadcn Pagination)
    │   └── DeleteSessionDialog (shadcn AlertDialog — shared for list + detail)
    └── [Detail View — on row click]
        ├── Back button + metadata header (username, session_id, started_at, source)
        ├── SessionMessageList
        │   └── Per message — reuses existing Chat renderers:
        │       ├── user_text / user_stt  → UserMessage
        │       ├── llm_thinking          → ThinkingMessage
        │       ├── llm_response          → AssistantMessage
        │       ├── ha_result             → ToolCallMessage
        │       └── tool_result           → ToolCallMessage
        └── Delete button (same DeleteSessionDialog, navigates back on confirm)
```

`ChatarchivSection` manages `view: 'list' | 'detail'` state internally. No router entry, no additional routing library.

---

### B) Data Model (plain language)

PROJ-51 provides the schema. This feature only reads and deletes — no new tables or columns.

**Sessions list** (last 30 days, all users, paginated):
Each row contains: session ID, user display name (current), started_at, session type (llm / ha_only), title (nullable), source (webapp_cc / webapp_mic / esphome), message count.

**Session detail**:
Same header fields plus: all messages in chronological order, each with msg_type, content, and created_at.

---

### C) API Endpoints (alice-chat-stream — Python)

Three new admin-only routes behind an admin middleware that verifies `alice.users.role = 'admin'` for the JWT-authenticated user:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/sessions?page=1&limit=20` | Paginated list — last 30 days, all users, newest first |
| `GET` | `/admin/sessions/{session_id}` | Full session with all messages |
| `DELETE` | `/admin/sessions/{session_id}` | Delete session + messages (CASCADE) |

Non-admin JWTs receive a `403`. Frontend tab hiding is UX only — the server enforces access.

---

### D) Tech Decisions

**Why alice-chat-stream, not n8n?**
alice-chat-stream already owns JWT verification and PostgreSQL access for session/message CRUD. Three new routes = ~20 lines of Python. A webhook-based n8n approach would add credential wiring and indirection with no benefit.

**Why offset-based pagination, not infinite scroll?**
This is a historical audit list, not a real-time feed. Offset pagination pairs naturally with the existing shadcn `Pagination` component and is simpler to implement correctly.

**Why reuse existing chat renderers?**
`ThinkingMessage`, `AssistantMessage`, `UserMessage`, `ToolCallMessage` already handle every msg_type PROJ-51 defines. Reusing them gives visual consistency with the main chat view at zero additional code.

---

### E) Dependencies

No new packages. All shadcn components already installed:
- `Table` — session list
- `Pagination` — page navigation
- `AlertDialog` — delete confirmation
- `Badge` — session type + source labels

## QA Test Results

**Tested:** 2026-06-17
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-A: Zugang & Navigation
- [x] AC-A1: "Chatarchiv" tab added in `SettingsPage.tsx`; rendered only when `role === "admin"` (conditional on `isAdmin` check in TSX)
- [x] AC-A2: Server-side `_require_admin` dependency on all 3 admin endpoints returns HTTP 403 for non-admin JWTs; client-side tab hiding is purely UX
- [x] AC-A3: Table uses responsive Tailwind classes; `max-w-[200px] truncate` for title column; layout adapts to mobile

#### AC-B: Listenansicht
- [x] AC-B1: Query `ORDER BY s.started_at DESC` + `WHERE started_at >= NOW() - INTERVAL '30 days'` — newest first, all users
- [x] AC-B2: Each row shows: username (display_name fallback), started_at (de-DE locale), session_type badge, title (or "—"), message_count, source label
- [x] AC-B3: 30-day filter applies to all session types; LLM sessions > 30 days old excluded
- [x] AC-B4: 20 rows/page; `Pagination` component with prev/next; hidden when totalPages ≤ 1
- [x] AC-B5: `Loader2` spinner while `loading === true`; empty state text "Keine Chats gefunden."
- [x] AC-B6: Trash icon per row; `e.stopPropagation()` prevents row click; `DeleteDialog` (AlertDialog) requires confirmation; reload after delete

#### AC-C: Detail-Ansicht
- [x] AC-C1: Row click → `handleSelect(session_id)` → `DetailView` with all messages in chronological order (`ORDER BY timestamp ASC`)
- [x] AC-C2: `mapAdminMessage()` maps msg_type → Message role; `MessageRenderer` renders each with correct visual style (user bubble, thinking, assistant, tool_call)
- [x] AC-C3: Metadata header shows username, source, session_type, started_at, session_id
- [x] AC-C4: `ChevronLeft` back button calls `onBack()` → restores list view; `selectedId` reset to null
- [x] AC-C5: Trash icon in detail view opens `DeleteDialog`; on confirm: `deleteAdminSession()` → `onBack()` returns to list
- [x] AC-C6: `mappedMessages.length === 0` → "Keine Nachrichten gespeichert." shown

### Edge Cases Status
- [x] Admin löscht LLM-Session: CASCADE delete in DB removes messages; session also disappears from affected user's sidebar (next load)
- [x] Session deleted between list and detail: `fetchAdminSessionMessages` returns 404 → `notFound=true` → "Session nicht mehr vorhanden." + implicit back button
- [x] Concurrent delete (two admins): second `DELETE FROM alice.sessions WHERE …` returns `DELETE 0` → 404 propagated to client
- [x] Sehr viele Sessions: offset pagination prevents full table scan; LIMIT applied server-side (max 100 enforced)
- [x] Session with only thinking tokens: `llm_thinking` messages shown via ThinkingMessage renderer
- [x] Username changed after chat: `COALESCE(u.display_name, u.username)` reads current users table on each query
- [x] Deleted user: CASCADE on `user_id` FK means orphaned sessions cannot appear

### Security Audit Results
- [x] All 3 admin endpoints enforce `_require_admin` via FastAPI `Depends` — server-side role check from JWT
- [x] session_id validated as UUID before use in both GET and DELETE endpoints; 400 returned on invalid format
- [x] Parameterized queries (`$1`, `$2`) throughout; no string interpolation in SQL
- [x] JWT `role` comes from verified RS256-signed token — cannot be spoofed by client
- [x] Tab is admin-only in frontend too (defense in depth) but server always enforces independently
- [x] `limit` capped at 100 server-side to prevent resource exhaustion

### Bugs Found

None.

### Summary
- **Acceptance Criteria:** 15/15 passed
- **Bugs Found:** 0
- **Security:** Pass
- **Production Ready:** YES
- **Recommendation:** Deploy together with PROJ-51 (requires SQL migration 014, alice-chat-stream redeploy, frontend redeploy)

## Deployment

**Deployed:** 2026-06-17

### Artifacts deployed
- `alice-chat-stream` container rebuilt (admin endpoints: `GET/DELETE /admin/sessions`, `GET /admin/sessions/{id}`)
- Frontend redeployed (`ChatarchivSection.tsx`, `SettingsPage.tsx`, `services/api.ts`)
- nginx config updated (new `location ^~ /api/admin/` block in `alice.conf`)

### Post-deployment bugs found and fixed

**Bug 1 — Admin API unreachable (Keine Chats gefunden):** `NEXT_PUBLIC_STREAM_API_URL=/api`, so `fetchAdminSessions` called `/api/admin/sessions`. nginx had no matching location for this path — it returned 404, which was silently caught, leaving the list empty. Fixed by adding `location ^~ /api/admin/` to `alice.conf` that strips `/api` and proxies to `alice-chat-stream:8003`.

**Bug 2 — Incorrect source labels:** `webapp_cc` was labelled "WebApp Tastatur" (wrong — CC is the voice conversation mode, not keyboard) and `webapp_mic` was labelled "WebApp Mikrofon" (wrong — MIC converts speech to text in the input field, equivalent to keyboard input). Fixed: `webapp_cc` → "WebApp CC", `webapp_mic` → "WebApp Tastatur". Source label also extended to display `esphome:Büro` as "ESPHome (Büro)" etc.
