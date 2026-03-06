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
_To be added by /qa_

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
