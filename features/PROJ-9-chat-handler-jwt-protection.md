# PROJ-9: Chat-Fenster & JWT-Schutz

## Status: Deployed
**Created:** 2026-02-28
**Last Updated:** 2026-02-28

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — JWT-Signierung, `alice_token` in localStorage, `auth.ts`

---

## Übersicht

Dieses Feature schließt zwei zusammenhängende Lücken:

1. **Chat-Fenster (Frontend):** Das erste nutzbare Chat-UI — Nachrichten eingeben, Antworten von Alice empfangen, neue Chats starten. Nach dem Login startet automatisch ein neuer Chat. Der "Neuer Chat"-Button in der Sidebar wird funktional.

2. **JWT-Schutz (Backend + Frontend):** Der `alice-chat-handler`-Webhook prüft den `Authorization: Bearer`-Header. Kein gültiges JWT → sofortiger 401. `user_id` kommt aus dem JWT-Claim, nicht mehr aus dem Body. Das Frontend sendet den Token automatisch mit und behandelt 401-Antworten mit Auto-Logout.

---

## User Stories

### Chat-Fenster
1. **Als Nutzer** möchte ich nach dem Login sofort ein Chat-Fenster sehen, ohne einen Button drücken zu müssen, damit ich ohne Umwege mit Alice sprechen kann.
2. **Als Nutzer** möchte ich eine Nachricht eingeben und absenden (Enter oder Button), damit ich Alice Fragen stellen kann.
3. **Als Nutzer** möchte ich Alices Antwort im Chat-Fenster sehen, sobald sie verfügbar ist, damit ich eine Konversation führen kann.
4. **Als Nutzer** möchte ich sehen, wenn Alice gerade antwortet (Typing Indicator), damit ich weiß dass meine Nachricht angekommen ist.
5. **Als Nutzer** möchte ich mit "Neuer Chat" in der Sidebar einen frischen Chat starten, damit ich Themen voneinander trennen kann.
6. **Als Nutzer** möchte ich meine bisherigen Chats in der Sidebar sehen (nach Datum gruppiert), damit ich frühere Gespräche wieder aufrufen kann.

### JWT-Schutz
7. **Als Nutzer** möchte ich, dass meine Chat-Anfragen automatisch mit meiner Authentifizierung gesendet werden, ohne dass ich mich darum kümmern muss.
8. **Als Nutzer** möchte ich bei einer abgelaufenen Session automatisch zum Login-Screen weitergeleitet werden, damit meine Daten geschützt bleiben.
9. **Als Admin** möchte ich, dass der Chat-Endpoint ohne gültiges JWT nicht erreichbar ist, damit unautorisierter Zugriff verhindert wird.
10. **Als Entwickler** möchte ich, dass `user_id` aus dem JWT-Claim gelesen wird (nicht aus dem Body), damit Clients ihre eigene `user_id` nicht manipulieren können.

---

## Acceptance Criteria

### Frontend — Chat-Fenster

- [ ] Nach dem Login wird automatisch ein neuer Chat gestartet (leeres Chat-Fenster sichtbar, keine manuelle Aktion nötig)
- [ ] Das Chat-Fenster zeigt eine leere Nachrichtenliste mit einem Willkommenshinweis wenn noch keine Nachrichten vorhanden sind
- [ ] Der Nutzer kann eine Nachricht in ein Texteingabefeld eingeben
- [ ] Absenden via Enter-Taste (ohne Shift) oder Send-Button
- [ ] Die eigene Nachricht erscheint sofort im Chat (rechts, User-Bubble)
- [ ] Während Alice antwortet, ist ein Typing Indicator sichtbar (links, als Platzhalter)
- [ ] Alices Antwort ersetzt den Typing Indicator und wird links angezeigt
- [ ] Das Send-Button und Eingabefeld sind während des laufenden Requests deaktiviert (kein Doppel-Submit)
- [ ] Bei einem Fehler (Netzwerk, 500) erscheint eine Fehlermeldung im Chat statt dem Typing Indicator
- [ ] Die Nachrichtenliste scrollt automatisch nach unten wenn neue Nachrichten erscheinen
- [ ] Der "Neuer Chat"-Button in der Sidebar erstellt eine neue Session und leert das Chat-Fenster
- [ ] Jede Session bekommt als Titel die ersten 40 Zeichen der ersten User-Nachricht
- [ ] Sessions erscheinen in der Sidebar-Liste (nach Datum gruppiert)
- [ ] Ein Klick auf eine Session in der Sidebar lädt deren Nachrichten ins Chat-Fenster

### Frontend — `services/api.ts`

- [ ] `services/api.ts` wird neu erstellt mit einer `sendMessage()`-Funktion
- [ ] Jeder Chat-Request enthält den Header `Authorization: Bearer <token>`
- [ ] Antwortet der Server mit HTTP 401 → Token löschen + `window.location.href = '/login'`
- [ ] Ist kein Token vorhanden → sofortiger Redirect zu `/login`, kein Request
- [ ] Bei Netzwerk-/Serverfehlern wird ein beschreibender Error geworfen

### Backend — n8n `alice-chat-handler`

- [ ] Der Webhook liest den `Authorization: Bearer <token>`-Header
- [ ] Fehlt der Header oder ist das Format ungültig → sofort HTTP 401, keine weitere Verarbeitung
- [ ] Das JWT wird mit `JWT_SECRET` verifiziert (Signatur + Ablaufzeit)
- [ ] Ungültiges oder abgelaufenes Token → HTTP 401
- [ ] `user_id` kommt aus dem JWT-Claim — der Body-Parameter `user_id` wird ignoriert
- [ ] `username` und `role` aus dem JWT stehen für Logging zur Verfügung
- [ ] Alle nachfolgenden Nodes verwenden `user_id` aus dem JWT

---

## Edge Cases

- **Seite wird neu geladen:** Session-Metadaten (id, title, updatedAt) bleiben via localStorage erhalten; Nachrichten innerhalb der Session gehen verloren (in-memory) — akzeptiert für Phase 1.5
- **Token läuft während Chat ab:** Nächste Anfrage erhält 401 → Auto-Logout + Redirect
- **Token fehlt beim Senden:** Kein Request, sofortiger Redirect
- **Manipulation von `user_id` im Body:** Serverseitig ignoriert — nur JWT-Claim zählt
- **Leere Nachricht absenden:** Send-Button bleibt deaktiviert solange Eingabe leer/nur Whitespace
- **Sehr lange Antwort von Alice:** Chat scrollt fortlaufend nach unten, kein Layout-Bruch
- **Netzwerkfehler während Typing:** Fehlermeldung als Chat-Nachricht (links), Eingabe wird wieder aktiviert
- **Session löschen:** Session wird aus Sidebar und localStorage entfernt; wenn aktiv → automatisch neuer Chat

---

## Technical Requirements

- **Nachrichten-Persistenz:** Session-Metadaten in `localStorage`; Nachrichten pro Session in React State (in-memory) — Vollpersistenz via DB ist PROJ-10+
- **JWT_SECRET:** Bereits als n8n-Umgebungsvariable gesetzt (PROJ-7)
- **Keine neuen npm-Pakete:** JWT-Verifikation in n8n via built-in `crypto`; `uuid` via `crypto.randomUUID()` (built-in)
- **Kein Token-Blacklisting:** Token läuft nach 24h ab (Phase 1.5)
- **Request-Format:** OpenAI-kompatibel — `{ messages: [...], session_id: "..." }` — `user_id` wird nicht mehr gesendet

---

## Neue und geänderte Dateien

| Datei | Änderung |
|---|---|
| `frontend/src/components/Chat/ChatWindow.tsx` | Neu — Container: MessageList + ChatInputArea |
| `frontend/src/components/Chat/MessageList.tsx` | Neu — scrollbare Nachrichtenliste mit Auto-Scroll |
| `frontend/src/components/Chat/MessageBubble.tsx` | Neu — User- (rechts) und Alice-Nachrichten (links) |
| `frontend/src/components/Chat/TypingIndicator.tsx` | Neu — Pulsierender "Alice antwortet..."-Indikator |
| `frontend/src/components/Chat/ChatInputArea.tsx` | Neu — Textarea + Send-Button |
| `frontend/src/hooks/useChatSessions.ts` | Neu — Session-State + localStorage-Sync |
| `frontend/src/services/api.ts` | Neu — sendMessage + Bearer-Header + 401-Handler |
| `frontend/src/components/Layout/AppShell.tsx` | Geändert — handleNewChat und Session-Management verdrahten |
| `frontend/src/app/page.tsx` | Geändert — Placeholder durch ChatWindow ersetzen |
| `workflows/core/alice-chat-handler.json` | Geändert — JWT Auth Guard + Unauthorized Response Node |

---

## Tech Design (Solution Architect)

### Übersicht

PROJ-9 besteht aus drei zusammenhängenden Teilen:

1. **Chat-Fenster (Frontend)** — neue Komponenten-Familie `Chat/` + Hook `useChatSessions`
2. **API-Service (Frontend)** — neue `services/api.ts` mit JWT-Header und 401-Handler
3. **JWT-Schutz (n8n)** — neuer Guard-Node im `alice-chat-handler`

---

### A) Frontend — Komponentenstruktur

```
AppShell (bestehend — erweitert)
├── Sidebar (bestehend — NewChatButton jetzt funktional)
│   ├── NewChatButton  → löst handleNewChat() aus
│   └── ChatList       → zeigt echte Sessions aus useChatSessions
└── Hauptbereich
    ├── [leer, kein aktiver Chat] → Empty State: "Starte einen neuen Chat"
    └── ChatWindow (NEU)
        ├── MessageList (NEU)
        │   ├── [leer] → Welcome Message: "Wie kann ich helfen?"
        │   ├── MessageBubble × n (NEU)
        │   │   ├── User-Nachricht  (rechts, grau)
        │   │   └── Alice-Antwort   (links, kein Bubble)
        │   └── TypingIndicator (NEU) — sichtbar während API-Call
        └── ChatInputArea (NEU)
            ├── Textarea (shadcn, auto-resize)
            └── Send-Button (shadcn, deaktiviert während Loading)
```

---

### B) Auto-Start nach Login

Nach einem erfolgreichen Login landet der Nutzer auf `/`. Die `AppShell` prüft beim Mounten:

```
AppShell mountet
  └── Keine aktive Session?
        → handleNewChat() automatisch aufrufen
        → Neues ChatWindow mit leerer Nachrichtenliste öffnen
```

Das heißt: der Nutzer sieht nach dem Login sofort ein leeres Chat-Fenster mit Eingabefeld — kein Klick nötig.

---

### C) Session-Datenmodell

**Wo gespeichert:** Session-Metadaten in `localStorage`; Nachrichten in React State (in-memory).

```
Session (localStorage):
  id        — UUID (crypto.randomUUID())
  title     — erste 40 Zeichen der ersten User-Nachricht
  updatedAt — Zeitstempel der letzten Aktivität

Nachrichten (React State, pro Session):
  role      — "user" oder "assistant"
  content   — Nachrichtentext
  timestamp — Zeitstempel
```

**Warum localStorage für Metadaten, State für Nachrichten?**
Sessions bleiben nach Page-Reload in der Sidebar sichtbar. Nachrichten-Persistenz (DB-Anbindung) ist PROJ-10+. Für Phase 1.5 ist der Verlust von Nachrichten nach Reload akzeptiert.

---

### D) Hook `useChatSessions`

Neuer Hook der die gesamte Session-Logik kapselt und von `AppShell` genutzt wird:

```
useChatSessions gibt zurück:
  sessions          — Liste aller Sessions (aus localStorage)
  activeSessionId   — aktive Session-ID
  messages          — Nachrichten der aktiven Session (aus State)
  isLoading         — true während API-Call läuft
  createNewSession()  → neue Session anlegen + aktivieren
  selectSession(id)   → andere Session aktivieren
  deleteSession(id)   → Session entfernen
  sendMessage(text)   → Nachricht senden (ruft api.ts auf)
```

---

### E) Nachrichtenfluss (sendMessage)

```
Nutzer sendet Nachricht
  ↓
useChatSessions.sendMessage(text)
  ├── User-Nachricht sofort in State hinzufügen (optimistic)
  ├── isLoading = true → TypingIndicator sichtbar
  ├── api.ts.sendMessage(allMessages, sessionId)
  │     → POST /api/webhook/v1/chat/completions
  │         Header: Authorization: Bearer <token>
  │         Body: { messages: [...], session_id }
  ├── Bei 401 → clearToken() + window.location.href = '/login'
  ├── Bei Fehler → Fehler-Nachricht in State einfügen
  └── Bei Erfolg → Alice-Antwort in State einfügen
        isLoading = false → TypingIndicator verschwindet
```

---

### F) n8n Workflow — Geänderter Ablauf

**Aktuell:**
```
Webhook → Input Validator (user_id aus Body) → Empty Check → [...]
```

**Nach PROJ-9:**
```
Webhook (JWT-Auth nativ aktiviert)
  ├── Kein / ungültiger / abgelaufener Token
  │     → n8n gibt automatisch HTTP 401 zurück
  │         [Workflow endet hier — kein extra Node nötig]
  └── Gültiger Token → Workflow läuft weiter
  ↓
[NEU] JWT Claims Extractor (Code Node — nur dekodieren, nicht verifizieren)
  → liest user_id, username, role aus dem bereits verifizierten Payload
  ↓
Input Validator (geändert: user_id aus JWT-Claims, nicht Body)
  ↓
Empty Input Check
  ↓
[... Rest unverändert ...]
```

**JWT-Verifikation:** Nativ im Webhook-Node über n8n's eingebaute JWT-Credential. n8n unterstützt HS256 und weitere Algorithmen direkt — kein Code-Node, kein `crypto`, kein externes npm-Paket.

**JWT-Credential in n8n:** ✅ Erledigt — Credential wurde in n8n unter *Credentials → JWT* angelegt (Key Type: Passphrase, Algorithm: HS256, Secret aus `.env`). Gleichzeitig wurde `JWT_SECRET` in `alice-auth/.env` nachgetragen und der Container neu gestartet. Bestehende Tokens (mit leerem Secret signiert) sind damit ungültig — einmalig aus- und wieder einloggen.

**JWT Claims Extractor:** Ein einfacher Code-Node der den mittleren Teil des Tokens (Payload) base64url-dekodiert und die Claims als Felder weitergibt. Keine Kryptographie — die Verifikation hat der Webhook-Node bereits erledigt.

---

### G) Request-Format (vorher/nachher)

| Feld | Vorher | Nachher |
|---|---|---|
| Header `Authorization` | — | `Bearer <jwt>` (required) |
| Body `messages` | ✅ bleibt | ✅ bleibt |
| Body `session_id` | ✅ bleibt | ✅ bleibt |
| Body `user_id` | gesendet (unsicher) | entfernt |

---

### H) Tech-Entscheidungen

| Entscheidung | Begründung |
|---|---|
| Chat-Komponenten unter `components/Chat/` | Klare Trennung vom bestehenden Sidebar/Auth-Code; eigener Namespace |
| Session-Metadaten in localStorage | Sidebar bleibt nach Page-Reload nutzbar; volle DB-Persistenz ist PROJ-10 |
| Nachrichten in React State (in-memory) | Einfachste Lösung für Phase 1.5; verhindert Over-Engineering |
| `useChatSessions`-Hook statt Context | Single-Responsibility; AppShell ist der einzige Consumer |
| Auto-Start nach Login im AppShell-Mount | Nutzer wartet nach Login nicht auf manuellen Klick — direkter Einstieg |
| n8n nativer JWT-Auth auf Webhook (kein Code-Node) | n8n hat eingebaute JWT-Verifikation inkl. HS256 — kein Custom-Code, kein `crypto`, automatisches 401 |
| `window.location.href` bei 401 | Vollständiger Page-Reload löscht State sauber; konsistent mit PROJ-7 |

---

### I) Keine neuen npm-Pakete

Alle benötigten Abhängigkeiten sind bereits installiert:

| Was | Woher |
|---|---|
| `uuid` für Session-IDs | `crypto.randomUUID()` — Browser built-in |
| JWT-Payload lesen | `jose` — bereits installiert (PROJ-7) |
| UI-Komponenten | `shadcn/ui` — Textarea, Button, ScrollArea bereits vorhanden |
| Icons | `lucide-react` — bereits installiert |

## QA Test Results

**Tested:** 2026-02-28
**Method:** Static code review + build verification (no running instance available)
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Frontend -- Chat-Fenster

#### AC-1: Auto-Start nach Login
- [x] `AppShell` uses `useEffect` on mount to call `createNewSession()` if no sessions exist
- [x] If sessions exist but none is active, the most recent session is auto-selected
- [x] Guard via `autoStarted.current` ref prevents duplicate session creation in StrictMode

#### AC-2: Leere Nachrichtenliste mit Willkommenshinweis
- [x] `MessageList` renders empty state with `MessageSquare` icon and "Wie kann ich helfen?" text when `messages.length === 0`

#### AC-3: Texteingabefeld
- [x] `ChatInputArea` renders a `Textarea` (shadcn) with placeholder "Nachricht eingeben..."
- [x] Has `aria-label="Nachricht eingeben"` for accessibility

#### AC-4: Absenden via Enter oder Send-Button
- [x] `handleKeyDown` checks `e.key === "Enter" && !e.shiftKey` and calls `handleSend()`
- [x] Send `Button` with `onClick={handleSend}` present
- [x] Shift+Enter does NOT send (allows multiline)

#### AC-5: Eigene Nachricht sofort sichtbar (rechts, User-Bubble)
- [x] `sendMessage` in hook adds user message to state optimistically before API call
- [x] `MessageBubble` renders user messages with `justify-end` (right-aligned) and `bg-gray-600`

#### AC-6: Typing Indicator sichtbar waehrend Antwort
- [x] `TypingIndicator` rendered in `MessageList` when `isLoading === true`
- [x] Uses animated bouncing dots with staggered delays
- [x] Has `aria-label="Alice antwortet"` and `sr-only` text

#### AC-7: Alices Antwort ersetzt Typing Indicator
- [x] On success, `isLoading` set to `false` (removes TypingIndicator) and assistant message added to state
- [x] Assistant messages rendered with `justify-start` (left-aligned), no bubble background (`bg-transparent`)

#### AC-8: Send-Button und Eingabefeld deaktiviert waehrend Request
- [x] `ChatInputArea` receives `disabled={isLoading}` prop
- [x] `Textarea` has `disabled={disabled}` attribute
- [x] Send button disabled via `!canSend` which includes `!disabled` check
- [x] `sendMessage` in hook has early return if `isLoading` is true (double-submit guard)

#### AC-9: Fehlermeldung im Chat bei Fehler
- [x] `catch` block in `sendMessage` creates error message with `role: "error"` in state
- [x] `MessageBubble` renders error role with red styling, `AlertCircle` icon

#### AC-10: Auto-Scroll bei neuen Nachrichten
- [x] `MessageList` uses `bottomRef` with `scrollIntoView({ behavior: "smooth" })` triggered by `useEffect` on `[messages, isLoading]`

#### AC-11: "Neuer Chat"-Button in Sidebar
- [x] `handleNewChat()` in `AppShell` calls `createNewSession()` and closes mobile drawer
- [x] `NewChatButton` in Sidebar wired to `onNewChat` prop

#### AC-12: Session-Titel = erste 40 Zeichen der ersten User-Nachricht
- [x] `sendMessage` in hook updates title with `text.trim().slice(0, 40)` on first user message
- [x] Condition checks `s.title === "Neuer Chat"` and no existing user messages

#### AC-13: Sessions in Sidebar gruppiert nach Datum
- [x] `ChatList` has `groupByDate()` function with groups: "Heute", "Gestern", "Diese Woche", "Aelter"
- [x] Groups rendered with uppercase labels

#### AC-14: Klick auf Session laedt Nachrichten
- [x] `ChatListItem` calls `onSelect(session.id)` on click
- [x] `selectSession` in hook sets `activeSessionId`, causing `messages` computed value to switch
- [ ] BUG: Messages are in-memory only -- switching sessions shows empty chat (messages lost when switching away and back). See BUG-1.

#### Frontend -- services/api.ts

#### AC-15: api.ts neu erstellt mit sendMessage()
- [x] File exists at `frontend/src/services/api.ts` with exported `sendMessage()` function
- [x] Clean TypeScript interfaces for `ChatMessage` and `ChatCompletionResponse`

#### AC-16: Authorization Bearer Header
- [x] `Authorization: \`Bearer ${token}\`` header set on every request
- [x] Token retrieved via `getToken()` from `auth.ts`

#### AC-17: HTTP 401 -> Token loeschen + Redirect
- [x] `res.status === 401` check present
- [x] Calls `clearToken()` then `window.location.href = "/login"`
- [x] Throws error after redirect to stop further processing

#### AC-18: Kein Token -> sofortiger Redirect
- [x] `if (!token)` check before `fetch` call
- [x] Redirects to `/login` and throws error

#### AC-19: Beschreibender Error bei Netzwerk-/Serverfehlern
- [x] Network errors caught with descriptive German message
- [x] Server errors (non-200, non-401) include status code in message
- [x] Missing assistant response throws "Keine Antwort von Alice erhalten."

#### Backend -- n8n alice-chat-handler

#### AC-20: Webhook liest Authorization Bearer Header
- [x] Webhook node has `"authentication": "jwt"` configured
- [x] Credential `"jwtAuth"` linked with id `"JWT_CREDENTIAL_ID"` and name `"Alice JWT"`

#### AC-21: Fehlender/ungueltiger Header -> HTTP 401
- [x] n8n native JWT auth on Webhook automatically returns 401 for missing/invalid tokens
- [x] No further processing occurs (handled before workflow execution)

#### AC-22: JWT mit JWT_SECRET verifiziert
- [x] JWT credential configured with HS256 algorithm per tech design docs
- [ ] BUG: Credential ID in JSON is placeholder `"JWT_CREDENTIAL_ID"` -- needs real n8n credential ID. See BUG-2.

#### AC-23: Ungueltiges/abgelaufenes Token -> 401
- [x] n8n native JWT verification handles expiry check automatically

#### AC-24: user_id aus JWT-Claim, Body-Parameter ignoriert
- [x] `JWT Claims Extractor` node decodes payload and extracts `user_id` from `payload.sub || payload.user_id`
- [x] `Input Validator` reads `$json.jwtClaims?.user_id` instead of `body.user_id`
- [x] Body `user_id` is never referenced in the updated Input Validator code

#### AC-25: username und role aus JWT verfuegbar
- [x] `JWT Claims Extractor` extracts `username` and `role` from JWT payload
- [x] `Input Validator` passes `username` and `role` downstream

#### AC-26: Alle nachfolgenden Nodes verwenden user_id aus JWT
- [x] `Input Validator` outputs `userId` from `jwtClaims.user_id`
- [x] Connection chain: `Webhook -> JWT Claims Extractor -> Input Validator -> ...`

### Edge Cases Status

#### EC-1: Seite wird neu geladen
- [x] Session metadata persisted in localStorage via `saveSessions()`
- [x] `loadSessions()` restores sessions on mount
- [x] Messages lost (in-memory) -- documented as accepted for Phase 1.5

#### EC-2: Token laeuft waehrend Chat ab
- [x] Next `sendMessage` call receives 401 -> `clearToken()` + redirect to `/login`

#### EC-3: Token fehlt beim Senden
- [x] `api.ts` checks `!token` before making request -> immediate redirect

#### EC-4: Manipulation von user_id im Body
- [x] Backend `Input Validator` reads `$json.jwtClaims?.user_id`, ignores body completely
- [x] Frontend does not send `user_id` in body at all (verified: no "user_id" in api.ts body)

#### EC-5: Leere Nachricht absenden
- [x] `canSend` computed as `value.trim().length > 0 && !disabled` -- empty/whitespace-only input keeps button disabled
- [x] `sendMessage` in hook has `!text.trim()` early return guard

#### EC-6: Sehr lange Antwort von Alice
- [x] `MessageBubble` uses `whitespace-pre-wrap break-words` CSS classes
- [x] Max-width constrained to `max-w-[85%] md:max-w-[70%]`
- [x] Auto-scroll triggered on message change

#### EC-7: Netzwerkfehler waehrend Typing
- [x] Error caught in `sendMessage` -> error message added to state as `role: "error"`
- [x] `isLoading` reset to `false` in `finally` block -> input re-enabled

#### EC-8: Session loeschen
- [x] `deleteSession` removes session from state and localStorage
- [x] If deleted session was active -> new session created automatically
- [ ] BUG: Race condition -- `deleteSession` calls `setSessions` twice (filter + add new). See BUG-3.

### Security Audit Results

#### Authentication
- [x] Frontend: `ProtectedRoute` wraps the main page, redirects unauthenticated users
- [x] Frontend: Every API request includes `Authorization: Bearer` header
- [x] Frontend: Missing token causes immediate redirect, no request made
- [x] Backend: Webhook has `"authentication": "jwt"` -- n8n verifies before workflow runs
- [x] 401 response triggers token cleanup and redirect

#### Authorization
- [x] `user_id` extracted from JWT claims server-side -- cannot be spoofed via body
- [x] Frontend does not send `user_id` in request body

#### Input Validation
- [x] Empty/whitespace-only messages blocked on client side
- [x] Empty messages also caught server-side by `Input Validator` + `Empty Input Check`
- [ ] BUG: No XSS sanitization on message content rendered via `{content}` in JSX. React auto-escapes JSX expressions, so this is safe -- NOT a bug. PASS.
- [x] React JSX auto-escapes rendered content -- XSS via message content not possible

#### Data Exposure
- [x] No secrets or credentials exposed in client-side code
- [x] JWT token stored in localStorage (consistent with PROJ-7 design decision)
- [ ] FINDING: localStorage is accessible to any JavaScript running on the same origin. An XSS vulnerability elsewhere could steal the token. This is a known trade-off documented in PROJ-7, not a new issue.

#### Rate Limiting
- [ ] BUG: No rate limiting on the chat endpoint. A user with a valid JWT could send unlimited requests, potentially overloading the LLM backend. See BUG-4.

#### Session Storage
- [x] Chat session data in localStorage is per-origin, not accessible cross-origin
- [ ] FINDING: Another user on the same browser (same origin) could read chat sessions from localStorage. Acceptable for local-first single-user system behind VPN.

### Regression Testing

#### PROJ-7 (JWT Auth / Login Screen)
- [x] `auth.ts` unchanged -- login/validate/logout functions intact
- [x] `ProtectedRoute` unchanged -- still wraps main page
- [x] Token storage key `alice_token` unchanged

#### PROJ-8 (Services Sidebar & Landing Page)
- [x] `Sidebar` component updated but backward-compatible (new props added: `onDeleteSession`)
- [x] `ServiceLinks` still present in Sidebar
- [x] `UserCard` still present in Sidebar
- [ ] BUG: `page.tsx` previously may have rendered a landing page placeholder; now it only renders `AppShell` with chat. No landing page content visible anymore. See BUG-5.

### Bugs Found

#### BUG-1: Switching sessions loses messages and shows empty chat
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Start a new chat and send a message
  2. Click "Neuer Chat" to create a second session
  3. Send a message in the second session
  4. Click the first session in the sidebar
  5. Expected: First session's messages are displayed
  6. Actual: Empty chat with "Wie kann ich helfen?" (messages are in-memory per session, but stored in `messagesBySession` which should work)
- **Analysis:** On closer review, `messagesBySession` is a React state object keyed by session ID. Switching sessions via `selectSession` only changes `activeSessionId`, and `messages` is derived from `messagesBySession[activeSessionId]`. This SHOULD work correctly as long as both sessions' messages are stored. Re-checking: the hook stores messages in `messagesBySession` state, which persists across session switches within the same page load. This is actually **NOT a bug** -- messages should persist during the same page session. Downgrading to informational: messages only lost on page reload (documented and accepted).
- **Status:** FALSE POSITIVE -- Retracted. Messages persist across session switches within the same page load.

#### BUG-2: Workflow JSON contains placeholder credential ID
- **Severity:** Low
- **Steps to Reproduce:**
  1. Open `workflows/core/alice-chat-handler.json`
  2. Check the Webhook node's credentials block
  3. Expected: Real n8n credential ID
  4. Actual: `"id": "JWT_CREDENTIAL_ID"` (placeholder string)
- **Impact:** The workflow JSON cannot be imported into n8n as-is without manually updating the credential reference. However, this is standard practice for version-controlled n8n workflows (credentials are environment-specific and not committed).
- **Priority:** Nice to have -- document the required manual step in deployment instructions

#### BUG-3: Potential double-render on session deletion
- **Severity:** Low
- **Steps to Reproduce:**
  1. Have an active session
  2. Delete it
  3. `deleteSession` calls `setSessions` with filter, then immediately calls `setSessions` again to add new session
  4. Expected: Single atomic state update
  5. Actual: Two separate `setSessions` calls may cause intermediate render with empty sessions array
- **Impact:** Minor visual flicker at most. React batches state updates in event handlers, so both `setSessions` calls in the same synchronous block should be batched. However, the function also calls `saveSessions()` directly inside the first `setSessions` updater, which is a side effect inside a state updater -- not idiomatic React.
- **Priority:** Nice to have

#### BUG-4: No rate limiting on chat endpoint
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Obtain a valid JWT
  2. Send rapid repeated requests to `/api/webhook/v1/chat/completions`
  3. Expected: Rate limiting after N requests
  4. Actual: All requests processed, potentially overloading Ollama/LLM backend
- **Impact:** A legitimate user (or compromised token) could DoS the LLM backend. Mitigated by VPN-only access.
- **Priority:** Fix in next sprint (Phase 2 security hardening)

#### BUG-5: Landing page content from PROJ-8 replaced
- **Severity:** Low
- **Steps to Reproduce:**
  1. Check `page.tsx` content
  2. Expected: May contain landing page elements from PROJ-8
  3. Actual: Only renders `ProtectedRoute > AppShell` (chat-focused)
- **Analysis:** PROJ-8 spec mentions "Services Sidebar & Landing Page Migration." Need to verify if the landing page was a separate route or the same `/` page. The PROJ-9 spec explicitly states: "Placeholder durch ChatWindow ersetzen" -- so this is intentional.
- **Status:** FALSE POSITIVE -- Intentional replacement per spec.

#### BUG-6: Auto-start race condition with localStorage sessions
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Have sessions stored in localStorage from a previous visit
  2. Reload the page
  3. `AppShell` useEffect runs with `autoStarted.current = false`
  4. `sessions` state is still `[]` (initial value) because `loadSessions` useEffect in the hook has not yet populated it
  5. Expected: Most recent session is selected
  6. Actual: `sessions.length === 0` evaluates to true, so a NEW session is created instead of selecting an existing one
- **Impact:** Every page reload creates a new "Neuer Chat" session even though existing sessions are in localStorage. The sidebar then shows the new session plus all old ones, leading to accumulation of empty sessions.
- **Root Cause:** The `useEffect` in `AppShell` (line 29-38) reads `sessions` from the hook, but the hook's own `useEffect` that loads from localStorage runs in the same render cycle. Due to React's useEffect ordering (child effects run before parent in some cases, but both are deferred), the `sessions` array is still empty `[]` when the auto-start effect checks `sessions.length === 0`.
- **Priority:** Fix before deployment -- this causes visible UX degradation

#### BUG-7: Rename button in ChatListItem is non-functional
- **Severity:** Low
- **Steps to Reproduce:**
  1. Hover over a chat session in the sidebar
  2. Click the pencil (rename) icon
  3. Expected: Some rename functionality or no button shown
  4. Actual: Button exists but the click handler is empty (comment says "Rename-Logik kommt in PROJ-8")
- **Impact:** Dead button that does nothing when clicked. Misleading UX.
- **Priority:** Nice to have -- remove or disable button until rename is implemented

### Cross-Browser Assessment (Static Analysis)

Since this is a static code review without a running instance, cross-browser testing is based on code analysis:

- **Chrome/Firefox/Safari:** All CSS uses standard Tailwind utilities. `crypto.randomUUID()` is supported in all modern browsers. `animate-bounce` is standard CSS animation. No browser-specific APIs used.
- **Responsive:** `ChatInputArea` uses `max-w-3xl mx-auto` for centered layout. `MessageBubble` uses `max-w-[85%] md:max-w-[70%]` breakpoint. Mobile header with hamburger menu at `md:hidden`. Sidebar uses `Sheet` for mobile drawer.

### Summary

- **Acceptance Criteria:** 24/26 passed (2 informational findings, 0 hard failures from code review)
- **Bugs Found:** 5 actionable (0 critical, 0 high, 2 medium, 3 low) -- BUG-1 and BUG-5 retracted as false positives
- **Security:** Pass with known trade-offs (localStorage JWT from PROJ-7, no rate limiting)
- **Build:** PASS -- `npm run build` compiles without errors
- **Production Ready:** NO -- BUG-6 (auto-start race condition) needs to be fixed first. It causes empty sessions to accumulate on every page reload.
- **Recommendation:** Fix BUG-6 (auto-start race condition) before deployment. BUG-4 (rate limiting) can be deferred to Phase 2. BUG-3 and BUG-7 are nice-to-have improvements.

## Deployment

**Deployed:** 2026-02-28
**Production URL:** https://alice.local/

### Changes Deployed
| Component | Action |
|---|---|
| Frontend (React) | Built + deployed to nginx via `./scripts/deploy-frontend.sh` |
| n8n `alice-chat-handler` | Full workflow update — JWT Claims Extractor node added, Input Validator updated, Webhook credential set to `4iUJhbFCSgQeHAGL` |

### Bug Fixes Included
| Bug | Fix |
|---|---|
| BUG-6 | Added `sessionsLoaded` flag to `useChatSessions`; `AppShell` auto-start waits for localStorage load before creating new session |
| BUG-3 | Removed `saveSessions()` side effect from inside `setSessions` state updater in `deleteSession` |
| BUG-2 | Replaced `JWT_CREDENTIAL_ID` placeholder with real n8n credential ID `4iUJhbFCSgQeHAGL` |

### Post-Deploy Verification
- [ ] Chat loads after login with no spurious empty sessions on reload
- [ ] Messages sent with valid JWT are processed correctly
- [ ] Expired/missing JWT returns 401 and triggers redirect to /login
- [ ] `user_id` in n8n logs matches JWT subject (not body)
