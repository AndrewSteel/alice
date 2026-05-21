# PROJ-12: Phase 2 Security & UX Hardening

## Status: Deployed
**Created:** 2026-03-02
**Last Updated:** 2026-03-02

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — nginx Auth-Routing muss stabil sein
- Requires: PROJ-9 (Chat-Handler JWT-Schutz) — Chat-Endpoint muss existieren

---

## Übersicht

Drei offene Punkte aus dem Sprint-Review (PROJ-1 bis PROJ-11) werden als gemeinsames Hardening-Feature umgesetzt:

1. **nginx Security Headers** — fehlende HTTP-Response-Header, die in jedem QA-Audit moniert wurden
2. **Rate-Limiting am Chat-Endpoint** — unbegrenzter LLM-Zugriff mit gültigem JWT
3. **Rename-Funktion in ChatListItem** — toter Stift-Button seit PROJ-9

Alle drei Punkte sind klein, isoliert testbar und betreffen keine Core-Logik. Sie erhöhen gemeinsam die Produktionsreife des Systems.

---

## User Stories

### Security Headers
1. **Als Admin** möchte ich, dass der Browser Frame-Einbettung von Alice verhindert, damit Clickjacking-Angriffe nicht möglich sind.
2. **Als Admin** möchte ich, dass der Browser keine MIME-Type-Sniffing-Angriffe durchführen kann, damit `X-Content-Type-Options: nosniff` gesetzt ist.
3. **Als Admin** möchte ich, dass Referer-Informationen kontrolliert weitergegeben werden, damit externe Dienste nicht unbeabsichtigt interne URLs sehen.
4. **Als Entwickler** möchte ich alle geforderten Security-Header in einem Audit-Check bestätigt sehen, damit die nginx Security Rules aus `.claude/rules/security.md` vollständig erfüllt sind.

### Rate-Limiting
5. **Als Admin** möchte ich, dass ein Nutzer nicht unbegrenzt Chat-Anfragen senden kann, damit der Ollama/LLM-Backend nicht überlastet werden kann.
6. **Als Nutzer** möchte ich bei Überschreitung des Limits eine verständliche Fehlermeldung erhalten (HTTP 429), damit ich weiß, dass ich kurz warten soll.
7. **Als Nutzer** möchte ich, dass das Limit großzügig genug ist, damit normales Chat-Verhalten (3–5 Nachrichten/Minute) nie geblockt wird.

### Chat Rename
8. **Als Nutzer** möchte ich den Titel eines Chats umbenennen, damit ich meine Gesprächshistorie sinnvoll organisieren kann.
9. **Als Nutzer** möchte ich den Rename direkt in der Sidebar durchführen, ohne einen Dialog zu öffnen, damit der Workflow schnell und frictionless ist.
10. **Als Nutzer** möchte ich den Rename mit Escape abbrechen können, damit ich versehentliche Titeländerungen rückgängig machen kann.

---

## Acceptance Criteria

### A) nginx Security Headers

Betroffene Datei: `docker/compose/infra/nginx/conf.d/alice.conf`

- [ ] `add_header X-Frame-Options "DENY" always;` ist im `server`-Block für Port 443 gesetzt
- [ ] `add_header X-Content-Type-Options "nosniff" always;` ist gesetzt
- [ ] `add_header Referrer-Policy "origin-when-cross-origin" always;` ist gesetzt
- [ ] Der bestehende `Strict-Transport-Security`-Header bleibt unverändert erhalten
- [ ] Die drei neuen Header sind mit `always` gesetzt (wirken auch bei 4xx/5xx-Antworten)
- [ ] Ein HTTP-Request-Tool (z.B. `curl -I`) bestätigt alle vier Security-Header in der Response

### B) Rate-Limiting am Chat-Endpoint

Betroffene Datei: `docker/compose/infra/nginx/conf.d/alice.conf`

- [ ] Eine `limit_req_zone`-Direktive definiert eine Zone auf Basis von `$binary_remote_addr` mit Rate **20r/m** (20 Requests pro Minute, ~1 alle 3 Sekunden)
- [ ] `limit_req_status 429;` ist konfiguriert (nicht der nginx-Default 503)
- [ ] Die `limit_req`-Direktive greift auf dem Location-Block `/api/webhook/` (der Chat-Endpoint `/api/webhook/v1/chat/completions`)
- [ ] `limit_req_zone` ist im `http`-Kontext, nicht im `server`-Block — betroffene Datei: `docker/compose/infra/nginx/nginx.conf` oder ein gemeinsames Snippet
- [ ] OPTIONS-Requests (CORS-Preflight) sind vom Rate-Limiting ausgenommen
- [ ] Eine Senderate von ≤ 20 Requests/Minute wird durchgelassen (kein 429)
- [ ] Eine Senderate von > 20 Requests/Minute erhält HTTP 429
- [ ] Die Frontend-Komponente `api.ts` zeigt bei HTTP 429 eine lesbare Fehlermeldung im Chat an (kein Auto-Logout — 429 ist kein 401)

### C) Chat-Session Rename

Betroffene Dateien: `frontend/src/components/Sidebar/ChatListItem.tsx`, `frontend/src/hooks/useChatSessions.ts`, ggf. `AppShell.tsx`, `ChatList.tsx`

- [ ] Klick auf den Stift-Button wechselt den Session-Titel in ein Inline-`<input>`-Feld mit dem aktuellen Titel vorausgefüllt
- [ ] Das Input-Feld ist beim Öffnen fokussiert und der Text ist selektiert
- [ ] Bestätigung: **Enter** oder **Blur** (Klick außerhalb) speichert den neuen Titel
- [ ] Abbrechen: **Escape** verwirft die Änderung und stellt den alten Titel wieder her
- [ ] Wird ein leerer String bestätigt, bleibt der alte Titel erhalten (kein leerer Chat-Titel)
- [ ] Der neue Titel wird in `localStorage` persistiert (via `useChatSessions.renameSession()`)
- [ ] Die `onRename`-Prop wird durch die Komponenten-Kette propagiert: `AppShell` → `Sidebar` → `ChatList` → `ChatListItem`
- [ ] Während des Rename-Modus löst ein Klick auf das Item keinen `onSelect` aus
- [ ] Das Rename-Input hat `aria-label="Chat umbenennen"` und `maxLength={60}`

---

## Edge Cases

- **Sehr langer Titel beim Rename:** Input hat `maxLength={60}`; Anzeige trunciert auf `max-w` wie bisher.
- **Rate-Limit und gleichzeitige Requests:** `limit_req burst=5 nodelay` erlaubt kurze Bursts (z.B. beim Seitenreload mehrere parallele Requests), ohne legitime Nutzung zu blockieren.
- **nginx.conf ist auf dem Server, nicht im Repo:** `limit_req_zone` muss im `http`-Kontext stehen; falls `nginx.conf` nicht in `docker/compose/infra/nginx/` liegt, kann die Zone alternativ mit einem `geo`-Block oder in einem separaten Snippet (`conf.d/rate-limit.conf`) definiert werden.
- **Security Header im `/v1/`-Location-Block:** nginx `add_header` gilt standardmäßig nicht für Location-Blöcke, die eigene `add_header`-Direktiven enthalten. Alle Location-Blöcke mit eigenen `add_header`-Direktiven müssen die Security Header ebenfalls explizit setzen — oder die Header werden via `always` im `server`-Block gesetzt und überschreiben nicht die Location-spezifischen CORS-Header.
- **Rename während eines laufenden Chats:** Rename ist nicht blockiert während isLoading=true; der Titel kann jederzeit geändert werden.
- **Session wird direkt nach dem Rename gelöscht:** Delete-Handler bleibt korrekt verdrahtet; kein Konflikt mit Rename-State.

---

## Technical Requirements

- **nginx:** Keine neuen Module erforderlich (`ngx_http_limit_req_module` ist im nginx-Default-Image enthalten)
- **Frontend:** Keine neuen npm-Pakete; shadcn `Input` oder natives `<input>` mit Tailwind-Styling
- **Kein Backend-Änderung:** Rate-Limiting läuft vollständig in nginx; n8n-Workflow bleibt unberührt
- **Deployment:** nginx-Config-Änderungen erfordern `nginx -s reload` (kein Container-Neustart nötig) oder Container-Neustart via `sync-compose.sh`
- **Rückwärtskompatibilität:** Alle bestehenden Endpoints und CORS-Einstellungen bleiben unverändert

---

## Tech Design (Solution Architect)

### Überblick

PROJ-12 besteht aus drei vollständig isolierten Änderungen ohne gegenseitige Abhängigkeiten. Sie können in beliebiger Reihenfolge implementiert werden.

---

### A) nginx Security Headers

**Was geändert wird:** Drei fehlende HTTP-Response-Header werden zur nginx-Konfiguration hinzugefügt.

**Das nginx-Vererbungsproblem:**
nginx hat eine wichtige Eigenschaft: Wenn ein `location`-Block eigene `add_header`-Direktiven definiert, erbt er **keine** `add_header`-Werte vom übergeordneten `server`-Block. In `alice.conf` haben alle sieben CORS-Location-Blöcke (`/v1/`, `/vtest/`, `/webhook-test/`, `/webhook/`, `/api/auth/`, `/api/webhook/`, `/webhook-waiting/`) eigene `add_header`-Direktiven — ein einfaches Hinzufügen der Security-Header im `server`-Block würde also für diese Locations nichts bewirken.

**Lösung — Snippet-Datei:**
Eine neue Datei `docker/compose/infra/nginx/snippets/security-headers.conf` wird erstellt, die die drei Header enthält. Anschließend wird diese Datei in `alice.conf` per `include` eingebunden — einmal im `server`-Block (für die `/`-Location) und einmal in jedem der sieben CORS-Location-Blöcke.

```
Neue Datei:
  snippets/security-headers.conf
    → X-Frame-Options: DENY
    → X-Content-Type-Options: nosniff
    → Referrer-Policy: origin-when-cross-origin

Geänderte Datei:
  conf.d/alice.conf
    → include snippets/security-headers.conf; (im server-Block)
    → include snippets/security-headers.conf; (in jedem CORS-Location-Block: 7×)
```

**Warum ein Snippet und nicht einfach wiederholen?**
Die drei Header-Zeilen würden sonst 7× redundant in der Datei stehen. Das Snippet-Muster ist der nginx-Standard für genau diesen Fall und macht künftige Änderungen (z.B. CSP-Header) zu einer einzeiligen Änderung.

**Deployment:** `nginx -s reload` nach `sync-compose.sh` (kein Container-Neustart nötig).

---

### B) Rate-Limiting am Chat-Endpoint

**Was geändert wird:** nginx begrenzt eingehende Chat-Requests auf 20 pro Minute pro IP-Adresse. Kurze Bursts von 5 Requests werden ohne Wartezeit durchgelassen.

**Komponentenplan:**

```
Neue Datei:
  conf.d/rate-limit.conf          ← wird vom nginx http-Block eingebunden
    → limit_req_zone (Zone "chat_limit", 20r/m, 10MB shared memory)

Geänderte Datei:
  conf.d/alice.conf
    → server-Block: limit_req_status 429;
    → /api/webhook/-Location: limit_req zone=chat_limit burst=5 nodelay;
```

**Warum eine separate Datei für die Zone?**
Die `limit_req_zone`-Direktive muss im `http`-Kontext stehen, nicht im `server`-Kontext. nginx lädt alle `conf.d/*.conf`-Dateien direkt in den `http`-Kontext, daher ist eine separate `rate-limit.conf` die sauberste Lösung — ohne die nginx-Hauptkonfigurationsdatei anfassen zu müssen.

**OPTIONS-Exemption (CORS-Preflight):**
Der bestehende `if ($request_method = OPTIONS) { return 204; }` im Location-Block terminiert den Request in der Rewrite-Phase. `limit_req` läuft in der späteren Access-Phase — OPTIONS-Requests erreichen rate-limiting daher nie und werden korrekt ausgenommen.

**Frontend-Fehlerbehandlung (429):**
In `frontend/src/services/api.ts` wird vor der generischen `!res.ok`-Prüfung ein spezifischer `res.status === 429`-Handler eingefügt:
- Zeigt die Nachricht `"Zu viele Anfragen — bitte kurz warten."` als Fehlerbubble im Chat
- Kein Token-Clear, kein Redirect (429 ist kein Auth-Fehler)
- Gleicher Mechanismus wie bestehende Netzwerkfehler (über `throw new Error()` → `messagesBySession` error-Role)

---

### C) Chat-Session Rename

**Komponentenplan (Prop-Kette, Top-Down):**

```
useChatSessions.ts
  + renameSession(id, newTitle)

AppShell.tsx
  + destructure renameSession aus Hook
  + handleRenameSession(id, newTitle)
  + onRenameSession={handleRenameSession} → sidebarProps

Sidebar.tsx
  + onRenameSession prop (SidebarProps)
  + onRename={onRenameSession} → ChatList

ChatList.tsx
  + onRename prop (ChatListProps)
  + onRename={onRename} → ChatListItem

ChatListItem.tsx
  + onRename prop (ChatListItemProps)
  + isRenaming state (boolean)
  + draft state (string)
  + Inline-Input statt <span> wenn isRenaming=true
```

**Datenfluss — renameSession im Hook:**
- Findet Session per ID, setzt neuen Titel wenn `newTitle.trim()` nicht leer
- `updatedAt` bleibt unverändert (kein Re-Sort durch Rename)
- Persistenz: Die bestehende `useEffect`-Logik in `useChatSessions` schreibt Sessions automatisch nach `localStorage`, sobald sich `sessions` ändert — keine zusätzliche Speicherlogik nötig

**ChatListItem — Inline-Edit-Verhalten:**

```
Pencil-Klick:
  → setIsRenaming(true)
  → setDraft(session.title)
  → Input rendert, ist fokussiert, Text selektiert

Während isRenaming=true:
  → <span> wird durch shadcn <Input> ersetzt
  → Outer-div onClick: if (isRenaming) return;  ← kein accidentelles onSelect
  → Hovered-Buttons ausgeblendet

Enter-Taste oder Blur:
  → draft.trim() nicht leer: onRename(session.id, draft.trim())
  → draft.trim() leer: kein onRename (alter Titel bleibt)
  → setIsRenaming(false)

Escape-Taste:
  → setIsRenaming(false)  ← draft verworfen, onRename wird NICHT aufgerufen
```

**UI-Komponenten:** shadcn `Input` (`frontend/src/components/ui/input.tsx`) ist bereits installiert. Kein neues npm-Paket notwendig.

---

### Dateiübersicht

| Datei | Änderungstyp | Scope |
|---|---|---|
| `nginx/snippets/security-headers.conf` | Neu erstellen | A |
| `nginx/conf.d/rate-limit.conf` | Neu erstellen | B |
| `nginx/conf.d/alice.conf` | Erweitern | A + B |
| `frontend/src/services/api.ts` | Erweitern (1 Case) | B |
| `frontend/src/hooks/useChatSessions.ts` | Erweitern (1 Funktion) | C |
| `frontend/src/components/Layout/AppShell.tsx` | Erweitern (1 Prop) | C |
| `frontend/src/components/Sidebar/Sidebar.tsx` | Erweitern (1 Prop) | C |
| `frontend/src/components/Sidebar/ChatList.tsx` | Erweitern (1 Prop) | C |
| `frontend/src/components/Sidebar/ChatListItem.tsx` | Refactor (Inline-Edit) | C |

**Keine neuen npm-Pakete. Keine neuen n8n-Workflows. Keine DB-Änderungen.**

## QA Test Results

**Tested:** 2026-03-06
**App URL:** https://alice.happy-mining.de
**Tester:** QA Engineer (AI)
**Method:** Code review + static analysis + build verification (no live server access)

### Acceptance Criteria Status

#### AC-A: nginx Security Headers

- [x] AC-A1: `add_header X-Frame-Options "DENY" always;` is set in the security-headers snippet and included in the server block for port 443 (alice.conf line 25)
- [x] AC-A2: `add_header X-Content-Type-Options "nosniff" always;` is set (snippet line 3)
- [x] AC-A3: `add_header Referrer-Policy "origin-when-cross-origin" always;` is set (snippet line 4)
- [x] AC-A4: The existing `Strict-Transport-Security` header remains unchanged (alice.conf line 24)
- [x] AC-A5: All three new headers use `always` keyword -- confirmed in `snippets/security-headers.conf`
- [x] AC-A6: Snippet is included in the server block AND in all 7 CORS location blocks (`/v1/`, `/vtest/`, `/webhook-test/`, `/webhook/`, `/api/auth/`, `/api/webhook/`, `/webhook-waiting/`), correctly solving the nginx header inheritance problem. Cannot run live `curl -I` from this environment, but code review confirms correct placement.

#### AC-B: Rate-Limiting am Chat-Endpoint

- [x] AC-B1: `limit_req_zone $binary_remote_addr zone=chat_limit:10m rate=20r/m;` defined in `conf.d/rate-limit.conf`
- [x] AC-B2: `limit_req_status 429;` configured in server block (alice.conf line 28)
- [x] AC-B3: `limit_req zone=chat_limit burst=5 nodelay;` applied to `/api/webhook/` location block (alice.conf line 134)
- [x] AC-B4: `limit_req_zone` is in `conf.d/rate-limit.conf` which is loaded in the `http` context (nginx auto-includes `conf.d/*.conf` in http context) -- not in the server block
- [x] AC-B5: OPTIONS requests are exempt. The `if ($request_method = OPTIONS) { return 204; }` executes in nginx's rewrite phase, which runs before the preaccess phase where `limit_req` operates. OPTIONS requests terminate before rate limiting is evaluated.
- [ ] AC-B6/B7: Cannot verify live rate-limit behavior (<=20r/m passes, >20r/m returns 429) without access to the running server. Requires manual testing.
- [x] AC-B8: `api.ts` has a dedicated `res.status === 429` handler (line 68-70) that throws `"Zu viele Anfragen -- bitte kurz warten."` -- no token clearing, no redirect. Error is caught by `useChatSessions.sendMessage()` catch block and displayed as an error message bubble.

#### AC-C: Chat-Session Rename

- [x] AC-C1: Pencil button click triggers `startRename()` which sets `isRenaming=true`, rendering a shadcn `<Input>` in place of the title `<span>` (ChatListItem.tsx lines 35-38, 66-79)
- [x] AC-C2: `useEffect` on `isRenaming` calls `inputRef.current.focus()` and `inputRef.current.select()` (ChatListItem.tsx lines 28-33)
- [x] AC-C3: Enter key calls `commitRename()` (line 73); `onBlur` also calls `commitRename()` (line 71) -- both save the new title
- [x] AC-C4: Escape key calls `cancelRename()` which sets `isRenaming(false)` without calling `onRename` (line 74, lines 47-49)
- [x] AC-C5: Empty string check: `commitRename()` only calls `onRename` if `draft.trim()` is truthy (line 41); `renameSession()` in the hook also guards with `if (!trimmed) return` (useChatSessions.ts line 99)
- [x] AC-C6: New title persisted in localStorage via the existing `useEffect` that calls `saveSessions(sessions)` whenever `sessions` state changes (useChatSessions.ts lines 66-72)
- [x] AC-C7: `onRename` prop propagated through full chain: `AppShell` (line 69) -> `Sidebar` (line 51) -> `ChatList` (line 73) -> `ChatListItem` (line 18)
- [x] AC-C8: During rename mode, the outer div's `onClick` checks `if (!isRenaming)` before calling `onSelect` (ChatListItem.tsx line 55); input click has `e.stopPropagation()` (line 76)
- [x] AC-C9: Input has `aria-label="Chat umbenennen"` and `maxLength={60}` (ChatListItem.tsx lines 77-78)

### Edge Cases Status

#### EC-1: Very long title during rename
- [x] Input has `maxLength={60}` enforced at the HTML level. Display uses `truncate` class on the span. Handled correctly.

#### EC-2: Rate-limit burst handling
- [x] `burst=5 nodelay` is configured (alice.conf line 134), allowing short bursts without blocking legitimate use.

#### EC-3: nginx.conf not in repo for limit_req_zone
- [x] Solved by placing the zone definition in `conf.d/rate-limit.conf` which nginx loads into the http context. Clean solution per the edge case spec.

#### EC-4: Security headers in location blocks with own add_header
- [x] Solved via `include snippets/security-headers.conf;` in every location block that has its own `add_header` directives. All 7 CORS locations include the snippet.

#### EC-5: Rename during active chat (isLoading=true)
- [x] No guard against isLoading in the rename flow. Rename is independent of chat state. Handled correctly per spec.

#### EC-6: Delete immediately after rename
- [x] Delete handler works on session ID, rename state is local to ChatListItem component. No conflict possible.

### Security Audit Results (Red Team)

- [x] Authentication: `api.ts` checks for JWT token before requests; 401 triggers token clear + redirect to login
- [x] Authorization: Chat sessions stored in localStorage per-browser; no cross-user data access possible in current architecture
- [x] XSS via rename input: Input uses React controlled component (`value={draft}`), no `dangerouslySetInnerHTML`. React auto-escapes output in JSX. Safe.
- [x] Input injection via rename: Title is stored in localStorage only (client-side); never sent to server. No SQL injection vector.
- [x] 429 does not trigger auth bypass: 429 handler correctly does NOT clear token or redirect (api.ts line 68-70)
- [x] CORS headers present on 429 responses: `add_header ... always` applies to error responses including 429. Frontend can read the status code.
- [ ] BUG-1: HSTS header missing `includeSubDomains` (see below)
- [ ] BUG-2: No rate limiting on authentication endpoints (see below)
- [x] Security headers snippet does not contain sensitive information (comment on line 1 is benign)
- [x] No secrets exposed in frontend code or nginx config
- [ ] BUG-3: Rate-limit applies per IP, not per user (see below)

### Regression Testing

- [x] PROJ-7 (JWT Auth / Login): `auth.ts` unchanged, login flow intact. `api.ts` 401 handler still present and correctly positioned before the new 429 handler.
- [x] PROJ-8 (Services Sidebar): `ServiceLinks.tsx` component unchanged by PROJ-12. Sidebar prop chain extended but does not break existing props.
- [x] PROJ-9 (Chat-Handler JWT): Chat endpoint path `/api/webhook/v1/chat/completions` unchanged. JWT authorization header still proxied to n8n via `proxy_set_header Authorization`.
- [x] Frontend build: TypeScript compiles with zero errors. Production build succeeds (5 pages, all static).
- [x] CORS configuration: All location blocks retain their CORS headers unchanged. The snippet is added AFTER CORS headers, not replacing them.

### Bugs Found

#### BUG-1: HSTS header missing `includeSubDomains` directive
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Read `.claude/rules/security.md` line 23: requires "Strict-Transport-Security with includeSubDomains"
  2. Read `alice.conf` line 24: `add_header Strict-Transport-Security "max-age=31536000" always;`
  3. Expected: `"max-age=31536000; includeSubDomains"` per security rules
  4. Actual: `includeSubDomains` is absent
- **File:** `/home/stan/Apps/development/alice/docker/compose/infra/nginx/conf.d/alice.conf` line 24
- **Note:** This pre-dates PROJ-12 (AC-A4 says "HSTS remains unchanged"), but it contradicts the project security rules. Also affects `ollama-3090.conf`, `openwebui.conf`, `ollama-titan.conf`, and `snippets/ssl-opts.conf`.
- **Priority:** Fix in next sprint (pre-existing issue, not a PROJ-12 regression)

#### BUG-2: No rate limiting on authentication endpoints
- **Severity:** High
- **Steps to Reproduce:**
  1. Read `.claude/rules/security.md` line 14: "Implement rate limiting on authentication endpoints"
  2. Inspect `/api/auth/` location block in `alice.conf` (lines 113-125)
  3. Expected: A `limit_req` directive on the `/api/auth/` location, especially for `POST /api/auth/login`
  4. Actual: No rate limiting on auth endpoints. An attacker could brute-force login credentials at unlimited speed.
- **File:** `/home/stan/Apps/development/alice/docker/compose/infra/nginx/conf.d/alice.conf` lines 113-125
- **Note:** The PROJ-12 spec only specifies rate-limiting for the chat endpoint, so this is technically not a PROJ-12 acceptance criteria failure. However, the project security rules explicitly require it, and this is a significant security gap. A separate rate-limit zone (e.g., `auth_limit` at 5r/m) should be added to the `/api/auth/` location.
- **Priority:** Fix before deployment of next security-related feature (high risk of credential brute-force)

#### BUG-3: Rate-limit is per IP, not per authenticated user
- **Severity:** Low
- **Steps to Reproduce:**
  1. The rate-limit zone uses `$binary_remote_addr` (client IP)
  2. All users behind the same VPN or NAT share one IP address
  3. Expected: Rate limiting should ideally be per-user (using JWT subject or user_id)
  4. Actual: One user hitting the limit blocks ALL users on the same IP. Conversely, a user with multiple IPs (VPN + direct) gets double the quota.
- **Note:** Since access is VPN-only and the user base is small (family), this is acceptable for now. Per-user rate limiting would require extracting the JWT claim in nginx (e.g., via `ngx_http_auth_jwt_module` or a Lua script), which adds complexity. The per-IP approach matches the spec's `$binary_remote_addr` requirement.
- **Priority:** Nice to have (acceptable trade-off for current architecture)

#### BUG-4: Rename blur/Enter double-fire (cosmetic)
- **Severity:** Low
- **Steps to Reproduce:**
  1. Click pencil icon to enter rename mode
  2. Type a new title
  3. Press Enter
  4. `commitRename()` is called by the `onKeyDown` handler
  5. `setIsRenaming(false)` triggers React re-render, unmounting the Input
  6. The Input's `onBlur` fires during unmount, calling `commitRename()` a second time
  7. Expected: `commitRename()` called exactly once
  8. Actual: `commitRename()` called twice (but idempotent -- same title applied twice)
- **File:** `/home/stan/Apps/development/alice/frontend/src/components/Sidebar/ChatListItem.tsx` lines 40-45, 71-74
- **Note:** This is functionally harmless because `onRename` is idempotent and `setSessions` with the same value causes no visible effect. However, it results in an unnecessary state update cycle.
- **Priority:** Nice to have

### Cross-Browser Testing
- **Note:** Cannot perform live cross-browser testing (Chrome, Firefox, Safari) from this environment. The code uses standard React patterns, shadcn/ui Input component, and vanilla DOM events (`onBlur`, `onKeyDown`, `onClick`) that have universal browser support. No browser-specific APIs detected. The `crypto.randomUUID()` API (used in `useChatSessions.ts`) requires a secure context (HTTPS) -- confirmed via the TLS configuration.
- Recommendation: Manual cross-browser verification needed before marking fully tested.

### Responsive Testing
- **Note:** Cannot perform live responsive testing at 375px/768px/1440px breakpoints. Code review shows:
  - ChatListItem uses `truncate` class for text overflow -- works at all widths
  - Input component uses `h-6` fixed height, responsive within the sidebar's fixed 260px width
  - Sidebar width is fixed at `w-[260px]` on desktop and Sheet-based on mobile -- rename input inherits this constraint
  - No responsive breakpoint issues identified in code
- Recommendation: Manual responsive verification needed.

### Summary
- **Acceptance Criteria:** 17/18 passed (1 cannot be verified without live server -- AC-B6/B7 rate-limit functional test)
- **Bugs Found:** 4 total (0 critical, 1 high, 1 medium, 2 low)
  - BUG-1 (Medium): HSTS missing `includeSubDomains` -- pre-existing, not a PROJ-12 regression
  - BUG-2 (High): No rate limiting on auth endpoints -- security gap per project rules
  - BUG-3 (Low): Per-IP rate limiting shared across VPN users -- acceptable trade-off
  - BUG-4 (Low): Double commitRename on Enter -- cosmetic, functionally harmless
- **Security Audit:** 1 high finding (BUG-2), 1 medium finding (BUG-1)
- **Regression:** No regressions detected. PROJ-7, PROJ-8, PROJ-9 functionality intact.
- **Build:** TypeScript compiles cleanly. Production build succeeds.
- **Production Ready:** CONDITIONAL YES -- PROJ-12 implementation is correct and complete per its own spec. BUG-2 (auth rate-limiting) should be tracked as a separate follow-up feature since it was not part of PROJ-12's scope but represents a security gap identified during this audit.

## Deployment

**Deployed:** 2026-03-06
**Commit:** `b261ffa` — `deploy(PROJ-12): Phase 2 Security & UX Hardening`
**Production URL:** https://alice.happy-mining.de

### Deployed Changes
- `docker/compose/infra/nginx/snippets/security-headers.conf` — neu (Security Header Snippet)
- `docker/compose/infra/nginx/conf.d/rate-limit.conf` — neu (Rate-Limit Zone 20r/m)
- `docker/compose/infra/nginx/conf.d/alice.conf` — Snippet-Includes in allen 7 CORS-Locations + `limit_req` auf `/api/webhook/`
- `frontend/src/services/api.ts` — 429-Handler
- `frontend/src/hooks/useChatSessions.ts` — `renameSession()`
- `frontend/src/components/Layout/AppShell.tsx`, `Sidebar.tsx`, `ChatList.tsx`, `ChatListItem.tsx` — Rename-Prop-Kette + Inline-Edit

### Post-Deploy
- Sync zu Server via `./sync-compose.sh` erforderlich (nginx config + static files)
- Nach Sync: `nginx -s reload` oder Container-Neustart für rate-limit.conf + alice.conf
