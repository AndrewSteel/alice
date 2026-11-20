# PROJ-7: JWT Auth / Login Screen

## Status: Deployed
**Created:** 2026-02-27
**Last Updated:** 2026-02-28

## Implementation Progress

| Schicht                                  | Status   | Notizen                                                                          |
| ---------------------------------------- | -------- | -------------------------------------------------------------------------------- |
| Frontend (Next.js)                       | ✅ Fertig | 14 neue Dateien, Build sauber, User-Review ausstehend                            |
| Backend (`alice-auth` FastAPI-Container) | ✅ Fertig | `docker/compose/automations/alice-auth/` — Login, Validate, Logout implementiert |
| Datenbank (Migration)                    | ⬜ Offen  | sql/migrations/007-add-auth-columns.sql                                          |
| Chat-Handler JWT-Schutz                  | ⬜ Offen  | alice-chat-handler anpassen                                                      |

### Frontend — Implementierte Dateien

- `src/services/auth.ts` — Login/Logout/Validate API-Calls, Token in localStorage
- `src/hooks/useAuth.ts` — Convenience-Hook für AuthContext
- `src/components/Auth/AuthProvider.tsx` — JWT-Prüfung beim App-Start, Redirect-Logik
- `src/components/Auth/ProtectedRoute.tsx` — Route-Guard mit Skeleton-Loader
- `src/components/Auth/LoginForm.tsx` — Formular mit Passwort-Toggle, Fehlerbehandlung
- `src/app/login/page.tsx` — Login-Seite (mobile vollflächig, Tablet+ als Card)
- `src/components/Sidebar/Sidebar.tsx` + 6 Sub-Komponenten
- `src/components/Layout/AppShell.tsx` — Sidebar fest (Desktop) / Drawer (Mobile)
- `src/app/layout.tsx` — AuthProvider + Dark Mode als Standard
- `src/app/page.tsx` — ProtectedRoute + AppShell als Wrapper

## Dependencies
- Requires: PROJ-3 (HA-First Chat Handler) — schützt den bestehenden Chat-Webhook mit JWT-Validierung
- Requires: PostgreSQL `alice.users` Tabelle (bereits vorhanden, wird erweitert)

---

## Übersicht

Dieses Feature ersetzt den bisherigen "Auto-Login" (fest verdrahteter User `user1`) durch eine echte Passwort-basierte Authentifizierung mit JWT. Nutzer sehen bei nicht vorhandener/abgelaufener Session einen Login-Screen und werden nach erfolgreichem Login zur Chat-Ansicht weitergeleitet.

**Scope:** Phase 1.5 — kein WebAuthn, kein Speaker-ID, kein 2FA. Nur Username + Passwort.

---

## User Stories

1. **Als Nutzer** möchte ich mich mit Benutzername und Passwort einloggen, damit nur autorisierte Personen auf Alice zugreifen können.
2. **Als Nutzer** möchte ich nach dem Login direkt zur Chat-Ansicht weitergeleitet werden, damit ich ohne zusätzliche Schritte loslegen kann.
3. **Als Nutzer** möchte ich einen Logout-Button in der Sidebar sehen, damit ich meine Session bewusst beenden kann.
4. **Als Nutzer** möchte ich beim Öffnen von Alice (mit noch gültigem Token) direkt zum Chat gelangen, ohne erneut einloggen zu müssen.
5. **Als Nutzer** möchte ich bei abgelaufenem oder ungültigem Token automatisch zum Login-Screen weitergeleitet werden, damit meine Daten geschützt bleiben.
6. **Als Admin** möchte ich, dass Passwörter sicher als bcrypt-Hash in der Datenbank gespeichert werden, damit Klartextpasswörter niemals persistiert werden.
7. **Als Nutzer** möchte ich bei falschen Anmeldedaten eine klare Fehlermeldung erhalten (ohne Hinweis, ob Username oder Passwort falsch war), um Sicherheitsrisiken zu minimieren.

---

## Acceptance Criteria

### Login Screen
- [ ] Der Login-Screen zeigt ein Formular mit den Feldern "Benutzername" und "Passwort"
- [ ] Der Login-Button ist während des API-Calls deaktiviert (kein Doppel-Submit)
- [ ] Bei falschem Username oder Passwort erscheint die generische Meldung: *"Ungültige Anmeldedaten"* (kein Unterschied zwischen falshem User/Passwort)
- [ ] Bei Netzwerkfehler erscheint eine verständliche Fehlermeldung
- [ ] Nach erfolgreichem Login wird der Nutzer via `window.location.href` zu `/` weitergeleitet
- [ ] Das Passwortfeld hat einen "Passwort anzeigen"-Toggle (Auge-Icon)
- [ ] Der Login-Screen ist auf mobilen Geräten (375px) nutzbar

### Session-Verwaltung
- [ ] Nach erfolgreichem Login wird das JWT in `localStorage` unter dem Key `alice_token` gespeichert
- [ ] Das JWT enthält die Claims: `user_id`, `username`, `role`, `exp` (Ablaufzeit)
- [ ] Token-Gültigkeit: 24 Stunden nach Ausstellung
- [ ] Beim Laden der App wird das Token aus localStorage gelesen und validiert
- [ ] Ist kein Token vorhanden → Redirect zu `/login`
- [ ] Ist das Token abgelaufen oder ungültig → localStorage leeren + Redirect zu `/login`
- [ ] Ist das Token gültig → Chat-Ansicht wird angezeigt, kein Login-Screen

### Logout
- [ ] In der Sidebar gibt es einen Logout-Button (mit Icon + Label "Abmelden")
- [ ] Klick auf Logout: Token aus localStorage entfernen + Redirect zu `/login`
- [ ] Der Logout-Endpoint im Backend wird aufgerufen (fire-and-forget, kein Blocking)

### Backend (`alice-auth` FastAPI-Container)

> **Implementierung:** Ein dedizierter FastAPI-Container (`alice-auth`). nginx routet `/api/auth/*` direkt zum Container. Der Container hat Zugriff auf PostgreSQL über das `backend`-Netzwerk.

- [ ] `POST /auth/login` — nimmt `{username, password}` entgegen, gibt `{token, user}` zurück oder HTTP 401
- [ ] `GET /auth/validate` — prüft den JWT aus dem `Authorization: Bearer <token>`-Header, gibt `{valid: true, user}` oder HTTP 401 zurück
- [ ] `POST /auth/logout` — loggt das Logout-Ereignis (fire-and-forget, kein Token-Blacklisting in Phase 1.5)
- [ ] JWT wird mit `JWT_SECRET` env var signiert (HS256)
- [ ] Passwortvergleich erfolgt mit bcrypt (kein Timing-Attack-Risiko durch direkten Stringvergleich)

### Datenbank (alice.users Erweiterung)

- [ ] Spalte `password_hash VARCHAR(255)` (bcrypt, cost factor 12) wird zu `alice.users` hinzugefügt
- [ ] Spalte `last_login_at TIMESTAMPTZ` wird hinzugefügt und bei jedem erfolgreichen Login aktualisiert
- [ ] Spalte `is_active BOOLEAN DEFAULT TRUE` wird hinzugefügt; inaktive Accounts können sich nicht einloggen
- [ ] Migration ist idempotent (IF NOT EXISTS / Idempotenz-Schutz)

### Bestehender Chat-Handler

- [ ] Der `alice-chat-handler`-Webhook prüft den `Authorization: Bearer`-Header
- [ ] Requests ohne gültiges JWT erhalten HTTP 401
- [ ] Der `user_id`-Claim aus dem JWT wird für alle nachfolgenden DB-Abfragen verwendet (kein clientseitiger `user_id`-Parameter mehr)

---

## Edge Cases

- **Leere Felder beim Login:** Beide Felder sind required; der Submit-Button bleibt deaktiviert, solange eines leer ist
- **Token während aktiver Session abgelaufen:** Nächster Chat-Request erhält 401 → Frontend fängt 401 ab → localStorage leeren + Redirect zu `/login`
- **Nutzer öffnet `/login` mit gültigem Token:** Direkt-Redirect zu `/` (kein erneuter Login-Screen)
- **Passwort mit Sonderzeichen:** Login-Formular sendet Passwort as-is (kein Frontend-Encoding); bcrypt-Vergleich ist byte-safe
- **Inaktiver Account:** Login schlägt mit derselben generischen Meldung fehl wie falsches Passwort (kein Hinweis auf Account-Status)
- **Mehrere Tabs:** Token in localStorage gilt für alle Tabs; Logout in einem Tab loggt alle aus (beim nächsten Request)
- **Kein Rate-Limiting:** Da Alice nur über VPN erreichbar ist, wird auf Account-Sperrung bei Fehlversuchen verzichtet

---

## Technical Requirements

- **Sicherheit:** Passwörter werden ausschließlich als bcrypt-Hash (cost 12) gespeichert — niemals Klartext
- **JWT:** HS256-Signierung mit `JWT_SECRET`; Payload enthält `user_id`, `username`, `role`, `iat`, `exp`
- **Keine Refresh Tokens:** Access Token 24h gültig, danach manuelles Re-Login
- **HTTPS:** Alle Auth-Endpoints laufen über nginx mit TLS (bereits konfiguriert)
- **CORS:** `alice-auth`-Endpoints akzeptieren Requests vom Frontend-Origin (nginx-Proxy handelt CORS)
- **Browser Support:** Chrome, Firefox, Safari (aktuelle Versionen)
- **Performance:** Login-Response < 500ms (bcrypt + DB-Abfrage)

---

## Tech Design (Solution Architect)

### Überblick

Das Auth-System besteht aus drei unabhängigen Schichten, die sauber getrennt sind:

1. **Datenbank** — alice.users wird um Auth-Felder erweitert
2. **Backend (`alice-auth`)** — dedizierter FastAPI-Container übernimmt Login, Validierung und Logout
3. **Frontend (Next.js)** — Login-Seite + Auth-Kontext + geschützte Routen

Der Chat-Handler wird minimal angepasst: Er liest künftig `user_id` aus dem JWT-Claim statt aus dem Request-Body.

---

### A) Responsive Design (Mobile-First)

Das Frontend wird Mobile-First entwickelt — d.h. der Basis-CSS gilt für Smartphones, Breakpoints erweitern das Layout nach oben.

**Breakpoints:**

| Gerät      | Breite   | Login-Layout                                                 |
| ---------- | -------- | ------------------------------------------------------------ |
| Smartphone | ≥ 375px  | Formular vollflächig, kein Card-Frame, oben Logo             |
| Tablet     | ≥ 768px  | Formular als zentrierte Card (max 480px), grauer Hintergrund |
| Desktop    | ≥ 1280px | Identisch Tablet, optional subtiles Hintergrundbild/Muster   |

**Login-Screen Layout (schematisch):**

```
Mobile (375px)         Tablet (768px+)          Desktop (1280px+)
┌─────────────┐        ┌──────────────────┐     ┌──────────────────────┐
│  Alice Logo │        │                  │     │                      │
│             │        │  ┌────────────┐  │     │   ┌────────────┐     │
│ [Username ] │        │  │ Alice Logo │  │     │   │ Alice Logo │     │
│ [Password ] │        │  │            │  │     │   │            │     │
│ [ Login   ] │        │  │ [Username] │  │     │   │ [Username] │     │
│             │        │  │ [Password] │  │     │   │ [Password] │     │
│             │        │  │ [ Login  ] │  │     │   │ [ Login  ] │     │
└─────────────┘        │  └────────────┘  │     │   └────────────┘     │
                       └──────────────────┘     └──────────────────────┘
  Full-screen            Centered Card            Centered Card
  kein Rand              480px max-width          480px max-width
```

**Chat-Screen Layout nach Login** — angelehnt an Open WebUI (Referenz: [open-webui/open-webui](https://github.com/open-webui/open-webui)):

```
Mobile (< 768px)                Tablet/Desktop (≥ 768px)
┌──────────────────────┐        ┌────────────┬─────────────────────────┐
│ [≡]  Alice      [⚙] │        │            │  [Neuer Chat]  [Modell] │
│──────────────────────│        │  SIDEBAR   │─────────────────────────│
│                      │        │            │                         │
│   Chat-Nachrichten   │        │ [+] Neuer  │   Chat-Nachrichten      │
│   (scrollbar)        │        │     Chat   │   (scrollbar)           │
│                      │        │            │                         │
│   [Alice-Avatar]     │        │ ─────────  │   [Alice-Avatar]        │
│   Antwort-Text       │        │ Heute      │   Antwort-Text          │
│                      │        │  • Chat 1  │                         │
│   [User]             │        │  • Chat 2  │   [User]                │
│   Nachricht          │        │ Gestern    │   Nachricht              │
│                      │        │  • Chat 3  │                         │
│──────────────────────│        │            │─────────────────────────│
│ [📎] [Eingabe...] [→]│        │ [Avatar]   │ [📎] [Eingabe...   ] [→]│
└──────────────────────┘        │ Username   │                         │
  Sidebar als Drawer             └────────────┴─────────────────────────┘
  (Sheet, overlay)               Sidebar fest, 260px breit
```

**Sidebar-Struktur (von oben nach unten), angelehnt an Open WebUI:**

```
┌─────────────────────┐
│  🤖 Alice       [×] │  ← Logo + Name + Einklappen-Button
│─────────────────────│
│  [+] Neuer Chat     │  ← Primär-Aktion
│  [🔍] Suche         │  ← Chat-Suche
│─────────────────────│
│  Heute              │  ← Zeitgruppen-Header
│    Chat-Titel 1     │  ← Chat-Eintrag (hover: Edit/Delete)
│    Chat-Titel 2     │
│  Gestern            │
│    Chat-Titel 3     │
│  Diese Woche        │
│    ...              │
│                     │  ← Infinite Scroll
│─────────────────────│
│  [Avatar] Admin   │  ← User-Card (bottom)
│           Admin  [⚙]│  ← Role + Settings/Logout Dropdown
└─────────────────────┘
```

**Visuelles Design (angelehnt an Open WebUI):**

| Element             | Light Mode          | Dark Mode (Standard) |
| ------------------- | ------------------- | -------------------- |
| Sidebar-Hintergrund | `bg-gray-50`        | `bg-gray-900`        |
| Chat-Hintergrund    | `bg-white`          | `bg-gray-800`        |
| User-Nachricht      | `bg-blue-50` rechts | `bg-gray-700` rechts |
| Alice-Antwort       | links, kein Bubble  | links, kein Bubble   |
| Schrift             | `text-gray-900`     | `text-gray-100`      |
| Akzentfarbe         | `blue-600`          | `blue-500`           |

Dark Mode ist Standard (wie Open WebUI); Light Mode als Toggle möglich.

**Tailwind-Klassen-Strategie (Mobile-First):**

- Basis-Klassen gelten für Mobile: `flex flex-col w-full`
- Tablet-Erweiterung: `md:flex-row md:items-center md:justify-center md:bg-muted`
- Desktop-Feintuning: `lg:max-w-md` (Login-Card), `lg:w-[260px]` (Sidebar)

---

### A) Komponentenstruktur (Frontend)

```
src/app/
├── layout.tsx              (Root Layout — AuthProvider + ThemeProvider wraps alles)
├── page.tsx                (Chat-Hauptseite — ProtectedRoute wraps AppShell)
└── login/
    └── page.tsx            (Login-Seite — öffentlich zugänglich)

src/components/
├── Auth/
│   ├── AuthProvider.tsx    (Context: Token lesen, validieren, User-State halten)
│   ├── LoginForm.tsx       (Formular: Username + Passwort + Submit-Button)
│   └── ProtectedRoute.tsx  (Wrapper: redirect zu /login wenn kein Token)
├── Layout/
│   └── AppShell.tsx        (Haupt-Layout: Sidebar + Chat-Area nebeneinander)
├── Sidebar/
│   ├── Sidebar.tsx         (Container: Sidebar inkl. Drawer-Modus auf Mobile)
│   ├── SidebarHeader.tsx   (Logo "Alice" + Einklappen-Button)
│   ├── NewChatButton.tsx   (Primär-Aktion: neuen Chat starten)
│   ├── ChatSearch.tsx      (Suche durch bestehende Chats)
│   ├── ChatList.tsx        (Scrollbare Liste, gruppiert nach Datum: Heute/Gestern/…)
│   ├── ChatListItem.tsx    (Einzelner Chat-Eintrag mit hover Edit/Delete)
│   └── UserCard.tsx        (Avatar + Username + Role + Settings/Logout Dropdown)
└── Chat/
    └── ... (wird in späterem PROJ gebaut — Placeholder)

src/services/
├── auth.ts                 (Login-/Logout-/Validate-API-Calls)
└── api.ts                  (Chat-API — Authorization-Header wird ergänzt)

src/hooks/
└── useAuth.ts              (Convenience-Hook für AuthContext)
```

**Datenfluss beim App-Start:**
```
App lädt → AuthProvider prüft localStorage
    ├── Kein Token → Redirect zu /login
    ├── Token vorhanden → POST /webhook/auth/validate
    │       ├── 200 OK → User-State setzen → Chat-Seite zeigen
    │       └── 401 → Token löschen → Redirect zu /login
    └── (validate läuft im Hintergrund, Skeleton zeigen)
```

**Datenfluss Login:**
```
User gibt Credentials ein → POST /webhook/auth/login
    ├── 200 OK → Token in localStorage speichern → window.location.href = '/'
    └── 401 → Fehlermeldung "Ungültige Anmeldedaten" anzeigen
```

---

### B) Datenmodell

**alice.users (Erweiterung — 3 neue Spalten):**

| Spalte          | Typ                    | Bedeutung                                              |
| --------------- | ---------------------- | ------------------------------------------------------ |
| `password_hash` | TEXT                   | bcrypt-Hash (cost 12) des Passworts — niemals Klartext |
| `last_login_at` | TIMESTAMPTZ            | Zeitstempel des letzten erfolgreichen Logins           |
| `is_active`     | BOOLEAN (DEFAULT true) | Deaktivierte Accounts können sich nicht einloggen      |

Bestehende Spalten (`id`, `username`, `role`, usw.) bleiben unverändert.

**JWT-Payload (was im Token steht):**

| Claim      | Inhalt                          | Beispiel        |
| ---------- | ------------------------------- | --------------- |
| `user_id`  | UUID des Users                  | `"abc-123-..."` |
| `username` | Login-Name                      | `"user1"`     |
| `role`     | Berechtigungsstufe              | `"admin"`       |
| `iat`      | Ausgestellt um (Unix-Timestamp) | `1709000000`    |
| `exp`      | Läuft ab um (iat + 24h)         | `1709086400`    |

Token wird lokal gespeichert unter Key: **`alice_token`** in `localStorage`.

---

### C) Backend-Architektur (`alice-auth` FastAPI-Container)

> **Architektur-Entscheidung:** Implementierung eines dedizierten FastAPI-Microservice (`alice-auth`). Begründung: Klare Trennung der Verantwortlichkeiten, echte bcrypt-Unterstützung ohne Workarounds, testbar und wartbar.

**Container:** `docker/compose/automations/alice-auth/`

| Datei              | Zweck                                                 |
| ------------------ | ----------------------------------------------------- |
| `main.py`          | FastAPI-App mit allen Endpoints                       |
| `Dockerfile`       | Python 3.12-slim, uvicorn                             |
| `requirements.txt` | fastapi, uvicorn, bcrypt, PyJWT, psycopg2-binary      |
| `compose.yml`      | Netzwerke: `backend` + `automation`, Port 8002 intern |
| `.env`             | `POSTGRES_CONNECTION`, `JWT_SECRET`                   |

**Endpoints:**

```
POST /auth/login      → bcrypt-Vergleich + JWT-Ausgabe
GET  /auth/validate   → JWT-Verifikation + is_active-Check
POST /auth/logout     → Log-Eintrag (fire-and-forget)
POST /auth/hash-password  → Utility: bcrypt-Hash erzeugen (nur Docker-intern)
GET  /health          → Health-Check (DB + JWT_SECRET)
```

**`/auth/login`** (Ablauf):
```
POST /auth/login {username, password}
→ Input-Validierung (Pydantic, trimmen)
→ PostgreSQL: SELECT id, username, role, password_hash, is_active
              FROM alice.users WHERE username = %s
→ bcrypt.checkpw() — timing-sicher
    ├── Fehler → HTTP 401 "Ungültige Anmeldedaten"
    └── OK → UPDATE alice.users SET last_login = NOW()
           → jwt.encode(HS256, JWT_SECRET, 24h)
           → HTTP 200 {token, user: {id, username, role}}
```

**`/auth/validate`** (Ablauf):
```
GET /auth/validate  Authorization: Bearer <token>
→ jwt.decode() — Signatur + Ablaufzeit
    ├── Ungültig/abgelaufen → HTTP 401
    └── OK → SELECT is_active FROM alice.users WHERE id = user_id
             ├── Inaktiv → HTTP 401
             └── OK → HTTP 200 {valid: true, user: {id, username, role}}
```

**`/auth/logout`** (Ablauf):
```
POST /auth/logout  Authorization: Bearer <token>
→ jwt.decode() optional (fire-and-forget)
→ Log-Eintrag: user_id + timestamp
→ HTTP 200 {success: true}
(Kein Token-Blacklisting — Token läuft nach 24h natürlich ab)
```

**nginx-Routing (Frontend → alice-auth):**
```
/api/auth/login     → http://alice-auth:8002/auth/login
/api/auth/validate  → http://alice-auth:8002/auth/validate
/api/auth/logout    → http://alice-auth:8002/auth/logout
```

**`alice-chat-handler`** (Anpassung — noch offen):
```
Webhook (POST /webhook/v1/chat/completions)
→ [NEU] JWT aus Authorization-Header lesen + verifizieren
    └── Ungültig → HTTP 401 (sofort)
→ user_id aus JWT-Claim statt aus Body lesen
→ [Rest bleibt unverändert]
```

---

### D) Tech-Entscheidungen und Begründungen

| Entscheidung                                              | Warum                                                                                  |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Next.js App Router** statt eigene Router-Logik          | Bestehende Projektstruktur, `/login` als eigene Route ist sauber                       |
| **React Context (AuthProvider)** für User-State           | Einfachste Lösung ohne externe State-Library; Auth-State wird selten geändert          |
| **localStorage** statt httpOnly Cookie                    | VPN-only Umgebung, kein XSS-Risiko durch öffentliche Seiten; einfacher für PWA-Nutzung |
| **JWT-Validierung im Frontend** (exp-Check)               | Verhindert unnötige Netzwerk-Requests wenn Token bereits abgelaufen ist                |
| **JWT-Validierung im Backend** (validate-Endpoint)        | App-Start-Check ob User noch aktiv ist (is_active könnte sich geändert haben)          |
| **FastAPI-Container** (`alice-auth`) statt n8n Code-Nodes | Saubere Trennung, echte bcrypt-Bibliothek, testbar; n8n bleibt für Chat-Orchestrierung |
| **Kein Refresh Token**                                    | Einfachheit; 24h ist akzeptabel für Single-User VPN-System                             |
| **Generische Fehlermeldung**                              | Kein Hinweis ob Username oder Passwort falsch (Security Best Practice)                 |

---

### E) Neue Dateien / Änderungen

**Neue Dateien — Frontend:**
- `frontend/src/app/login/page.tsx` — Login-Seite
- `frontend/src/components/Auth/AuthProvider.tsx` — Auth-Kontext
- `frontend/src/components/Auth/LoginForm.tsx` — Login-Formular
- `frontend/src/components/Auth/ProtectedRoute.tsx` — Route-Guard
- `frontend/src/components/Layout/AppShell.tsx` — Haupt-Layout (Sidebar + Chat)
- `frontend/src/components/Sidebar/Sidebar.tsx` — Sidebar-Container inkl. Drawer
- `frontend/src/components/Sidebar/SidebarHeader.tsx` — Logo + Einklappen
- `frontend/src/components/Sidebar/NewChatButton.tsx` — Neuer Chat
- `frontend/src/components/Sidebar/ChatSearch.tsx` — Chat-Suche
- `frontend/src/components/Sidebar/ChatList.tsx` — Datums-gruppierte Chat-Liste
- `frontend/src/components/Sidebar/ChatListItem.tsx` — Einzelner Chat-Eintrag
- `frontend/src/components/Sidebar/UserCard.tsx` — User-Info + Logout-Dropdown
- `frontend/src/services/auth.ts` — Auth-API-Calls
- `frontend/src/hooks/useAuth.ts` — Auth-Hook

**Neue Dateien — Backend (`alice-auth` FastAPI-Container):**

- `docker/compose/automations/alice-auth/main.py` — FastAPI-App (Login, Validate, Logout, Health)
- `docker/compose/automations/alice-auth/Dockerfile` — Python 3.12-slim + uvicorn
- `docker/compose/automations/alice-auth/requirements.txt` — Abhängigkeiten
- `docker/compose/automations/alice-auth/compose.yml` — Container-Definition

**Neue Dateien — Datenbank:**

- `sql/migrations/007-add-auth-columns.sql` — DB-Migration (password_hash, last_login, is_active)

**Geänderte Dateien:**

- `frontend/src/app/layout.tsx` — AuthProvider hinzufügen ✅
- `frontend/src/app/page.tsx` — ProtectedRoute wrappen ✅
- `frontend/src/services/api.ts` — Authorization-Header zu Chat-Requests ⬜ noch offen
- `workflows/core/alice-chat-handler.json` — JWT-Validierung am Anfang ⬜ noch offen

---

### F) Abhängigkeiten (neue npm-Pakete)

| Paket          | Zweck                                                                                   |
| -------------- | --------------------------------------------------------------------------------------- |
| `jose`         | JWT-Dekodierung und Ablaufzeit-Prüfung im Frontend (kein Signing!)                      |
| `lucide-react` | Icons (Auge für Passwort-Toggle, LogOut für Sidebar) — wahrscheinlich bereits vorhanden |

Keine neuen Backend-Abhängigkeiten.

## QA Test Results (Re-test #1)

**Tested:** 2026-02-28 (Re-test)
**Previous Test:** 2026-02-27
**Tester:** QA Engineer (AI) -- Code Review + Static Analysis + Build Verification
**Build Status:** Frontend build succeeds (Next.js 15.5.12, static export, 0 errors, 0 warnings)

**Note:** Database migration and Chat-Handler JWT-Schutz remain marked "Offen" in the implementation progress table. This re-test verifies fixes for bugs found in round 1 and re-checks all acceptance criteria. Live end-to-end browser testing remains blocked until all layers are deployed.

---

### Bug Fix Verification (from Round 1)

| Bug                                              | Status       | Verification                                                                                                                                                                                                             |
| ------------------------------------------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| BUG-1: Network errors show wrong message         | FIXED        | `auth.ts` now throws `"NETWORK_ERROR"` on fetch failure (line 37); `LoginForm.tsx` catches it and shows "Verbindungsfehler -- bitte erneut versuchen" (line 31)                                                          |
| BUG-2: Migration column name mismatch            | FIXED        | Migration now uses `last_login_at` (line 20); `main.py` line 168 also uses `last_login_at` -- consistent with spec                                                                                                       |
| BUG-3: Chat handler JWT protection               | STILL OPEN   | Marked "Offen" in progress table -- out of scope for current deployment phase                                                                                                                                            |
| BUG-4: No 401 interceptor for chat API           | STILL OPEN   | `frontend/src/services/api.ts` still does not exist -- depends on BUG-3                                                                                                                                                  |
| BUG-5: Login page no redirect for auth users     | FIXED        | `login/page.tsx` now checks for valid token via `decodeJwt()` and calls `router.replace("/")` if not expired (lines 13-29)                                                                                               |
| BUG-6: /auth/hash-password unauthenticated       | FIXED        | Endpoint now requires admin JWT: `_extract_bearer_token()` + `_decode_jwt()` + role check `payload.get("role") != "admin"` returns 403 (lines 280-287)                                                                   |
| BUG-7: SQL injection in set-initial-passwords.sh | FIXED        | Script now uses psql `-v` variable binding: `-v "pw_hash=${hash}" -v "uname=${username}"` with `:'pw_hash'` / `:'uname'` syntax (lines 83-85). Additionally validates bcrypt hash format with regex before use (line 77) |
| BUG-8: No token revocation                       | ACKNOWLEDGED | Phase 1.5 limitation, deferred to Phase 3                                                                                                                                                                                |
| BUG-9: alice-auth .env not in .gitignore         | FIXED        | `.gitignore` now explicitly lists `docker/compose/automations/alice-auth/.env`                                                                                                                                           |

---

### Acceptance Criteria Status

#### AC-1: Login Screen
- [x] Der Login-Screen zeigt ein Formular mit den Feldern "Benutzername" und "Passwort" -- `LoginForm.tsx` renders labeled Input fields for username and password
- [x] Der Login-Button ist waehrend des API-Calls deaktiviert (kein Doppel-Submit) -- `isDisabled` is true when `isLoading` is true; button uses `disabled={isDisabled}`
- [x] Bei falschem Username oder Passwort erscheint die generische Meldung "Ungueltige Anmeldedaten" -- catch block sets "Ungueltige Anmeldedaten" for non-network errors (line 33)
- [x] Bei Netzwerkfehler erscheint eine verstaendliche Fehlermeldung -- auth.ts throws "NETWORK_ERROR", LoginForm shows "Verbindungsfehler -- bitte erneut versuchen" (FIXED from BUG-1)
- [x] Nach erfolgreichem Login wird der Nutzer via `window.location.href` zu `/` weitergeleitet -- `LoginForm.tsx` line 28 uses `window.location.href = "/"`
- [x] Das Passwortfeld hat einen "Passwort anzeigen"-Toggle (Auge-Icon) -- Eye/EyeOff icon toggle implemented with proper aria-label
- [x] Der Login-Screen ist auf mobilen Geraeten (375px) nutzbar -- Mobile-first layout, `max-w-sm` with full-screen on mobile, Card on tablet+

#### AC-2: Session-Verwaltung
- [x] Nach erfolgreichem Login wird das JWT in localStorage unter dem Key `alice_token` gespeichert -- `setToken()` in `auth.ts` uses `localStorage.setItem("alice_token", ...)`
- [x] Das JWT enthaelt die Claims: user_id, username, role, exp -- `_create_jwt()` in `main.py` sets all required claims including `iat`
- [x] Token-Gueltigkeit: 24 Stunden nach Ausstellung -- `JWT_EXPIRY_HOURS = 24` in `main.py`
- [x] Beim Laden der App wird das Token aus localStorage gelesen und validiert -- `AuthProvider.tsx` useEffect reads token and calls `validate()`
- [x] Ist kein Token vorhanden -> Redirect zu /login -- `AuthProvider.tsx` line 34: `router.replace("/login")`
- [x] Ist das Token abgelaufen oder ungueltig -> localStorage leeren + Redirect zu /login -- `AuthProvider.tsx` lines 43-53 handle both cases
- [x] Ist das Token gueltig -> Chat-Ansicht wird angezeigt, kein Login-Screen -- `ProtectedRoute` renders children when `user` is set

#### AC-3: Logout
- [x] In der Sidebar gibt es einen Logout-Button (mit Icon + Label "Abmelden") -- `UserCard.tsx` has DropdownMenuItem with LogOut icon and "Abmelden" label
- [x] Klick auf Logout: Token aus localStorage entfernen + Redirect zu /login -- `AuthProvider.logout()` calls `logoutService(token)` which calls `clearToken()`, then `router.replace("/login")`
- [x] Der Logout-Endpoint im Backend wird aufgerufen (fire-and-forget, kein Blocking) -- `auth.ts` `logout()` uses fire-and-forget fetch with `.catch(() => {})`

#### AC-4: Backend (alice-auth FastAPI-Container)
- [x] POST /auth/login -- `alice-auth-login.json` routes POST to alice-auth:8002/auth/login; `main.py` implements full login flow
- [x] GET /auth/validate -- `alice-auth-validate.json` routes GET to alice-auth:8002/auth/validate with Authorization header forwarding
- [x] POST /auth/logout -- `alice-auth-logout.json` routes POST to alice-auth:8002/auth/logout
- [x] JWT wird mit JWT_SECRET env var signiert (HS256) -- `main.py` uses `JWT_ALGORITHM = "HS256"` and reads `JWT_SECRET` from env
- [x] Passwortvergleich erfolgt mit bcrypt -- `main.py` line 156: `bcrypt.checkpw()` is used (timing-safe)

#### AC-5: Datenbank (alice.users Erweiterung)
- [x] Spalte password_hash VARCHAR(255) wird zu alice.users hinzugefuegt -- Migration adds `password_hash VARCHAR(255)`
- [x] Spalte last_login_at TIMESTAMPTZ wird hinzugefuegt -- Migration line 20: `ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ` (FIXED from BUG-2)
- [x] Spalte is_active BOOLEAN DEFAULT TRUE wird hinzugefuegt -- Migration adds `is_active BOOLEAN NOT NULL DEFAULT TRUE`
- [x] Migration ist idempotent (IF NOT EXISTS) -- All ALTER TABLE statements use `ADD COLUMN IF NOT EXISTS`

#### AC-6: Bestehender Chat-Handler (DEFERRED)
- [ ] DEFERRED: Der alice-chat-handler-Webhook prueft den Authorization: Bearer-Header -- marked "Offen" in progress table; will be implemented separately
- [ ] DEFERRED: Requests ohne gueltiges JWT erhalten HTTP 401 -- depends on above
- [ ] DEFERRED: Der user_id-Claim aus dem JWT wird fuer alle nachfolgenden DB-Abfragen verwendet -- depends on above

---

### Edge Cases Status

#### EC-1: Leere Felder beim Login
- [x] Handled correctly -- `isDisabled` checks `!username.trim() || !password.trim()`, button stays disabled

#### EC-2: Token waehrend aktiver Session abgelaufen
- [ ] DEFERRED: No `api.ts` with 401 interceptor yet -- depends on Chat-Handler JWT integration (AC-6)

#### EC-3: Nutzer oeffnet /login mit gueltigem Token
- [x] Handled correctly -- `login/page.tsx` now checks token expiry via `decodeJwt()` and redirects to `/` if valid (FIXED from BUG-5)

#### EC-4: Passwort mit Sonderzeichen
- [x] Handled correctly -- `LoginForm` sends password as-is, bcrypt in Python uses `encode("utf-8")` which is byte-safe

#### EC-5: Inaktiver Account
- [x] Handled correctly -- `main.py` line 147-149: inactive users get the same generic "Ungueltige Anmeldedaten" error

#### EC-6: Mehrere Tabs
- [x] Handled correctly -- Token in localStorage is shared across all tabs; logout clears token, next request in other tab will fail validation

#### EC-7: Kein Rate-Limiting
- [x] Acknowledged -- VPN-only environment, no rate limiting by design

---

### Security Audit Results (Red Team)

#### Authentication
- [x] Login endpoint uses bcrypt with cost factor 12 for password hashing (`bcrypt.gensalt(rounds=12)`)
- [x] JWT signing uses HS256 with configurable secret from environment variable
- [x] Generic error messages on login failure (no username/password differentiation)
- [x] Inactive account check in both login and validate flows
- [x] Token expiration enforced both client-side (jose decodeJwt) and server-side (PyJWT decode)
- [x] `/auth/hash-password` endpoint now requires admin JWT + role check (FIXED from BUG-6)

#### Authorization
- [ ] DEFERRED: Chat handler does not yet enforce JWT -- marked "Offen" in progress table, will be separate implementation

#### Input Validation
- [x] `LoginRequest` Pydantic model validates username and password are strings
- [x] Username is trimmed before DB lookup (`body.username.strip()`)
- [x] Parameterized SQL queries in `main.py` (no SQL injection via login)
- [x] `set-initial-passwords.sh` now uses psql variable binding with bcrypt format validation (FIXED from BUG-7)

#### Token Security
- [x] JWT stored in localStorage (acceptable per spec: VPN-only, no public XSS surface)
- [x] Token cleared on logout and on validation failure
- [x] No token revocation -- acknowledged Phase 1.5 limitation (BUG-8, deferred to Phase 3)

#### Network Security
- [x] alice-auth container only on `backend` and `automation` networks (not exposed to frontend network)
- [x] n8n webhooks proxy through nginx (TLS already configured per CLAUDE.md)
- [x] JWT_SECRET passed via environment variable, not hardcoded
- [x] `.gitignore` explicitly lists `docker/compose/automations/alice-auth/.env` (FIXED from BUG-9)

#### Security Headers
- [x] Not directly applicable to this feature (handled at nginx level per CLAUDE.md)

---

### Additional Findings (Code Quality)

#### FINDING-1: Architecture Deviation from Spec (Informational, unchanged)
- The spec originally described n8n Code-Nodes for bcrypt handling, but the implementation uses a dedicated FastAPI microservice (`alice-auth`). This is architecturally superior. The spec has been updated to reflect this decision. Not a bug.

#### FINDING-2: AuthProvider uses router.replace for redirects (Informational, unchanged)
- `LoginForm` correctly uses `window.location.href` for post-login redirect. `AuthProvider.tsx` uses `router.replace("/login")` for pre-login redirects -- this is acceptable and actually preferred (avoids full page reload for redirect-to-login flows).

#### FINDING-3: Dockerfile uses Python 3.11-slim (Informational, NEW)
- The spec says "Python 3.12-slim" but the Dockerfile uses `python:3.11-slim`. Functionally equivalent for this use case, but should be updated to match the spec for consistency. Not a blocking issue.

---

### Remaining Open Items (Not Bugs -- Deferred Scope)

These items are explicitly marked "Offen" in the implementation progress table and are not bugs in the current implementation. They represent deferred scope that should be tracked as a follow-up ticket:

1. **Chat-Handler JWT-Schutz** (AC-6) -- `alice-chat-handler` n8n workflow needs JWT validation at the webhook entry point
2. **api.ts Authorization Header** (EC-2) -- Frontend `services/api.ts` needs to include Bearer token in chat requests and handle 401 responses with auto-logout
3. **Database Migration Execution** -- `sql/migrations/007-add-auth-columns.sql` needs to be run against the production database

---

### Cross-Browser Testing
- **Status:** BLOCKED -- Cannot perform live browser testing until all layers (Backend + Database) are deployed
- **Note:** Code uses standard HTML form elements, shadcn/ui components (Radix primitives), and Tailwind CSS. No browser-specific APIs detected. Expected to work in Chrome, Firefox, Safari.

### Responsive Testing
- **Status:** PARTIALLY VERIFIED via code review
- **375px (Mobile):** LoginForm uses `max-w-sm`, full-screen layout on mobile (no Card frame). AppShell uses Sheet drawer for sidebar. Mobile header with hamburger menu.
- **768px (Tablet):** Login uses `md:bg-gray-800 md:rounded-xl md:shadow-xl md:p-8` for Card appearance. Sidebar is fixed 260px.
- **1440px (Desktop):** Same as tablet layout. Spec says `max-w-md` for Login Card at desktop but implementation uses `max-w-sm` (384px vs 448px) -- minor deviation, not a bug.

---

### Summary
- **Acceptance Criteria:** 22/25 passed, 0 failed, 3 deferred (Chat-Handler JWT integration marked "Offen")
- **Bugs Fixed Since Round 1:** 6 of 9 fixed (BUG-1, BUG-2, BUG-5, BUG-6, BUG-7, BUG-9)
- **Bugs Remaining:** 3 total -- all deferred scope, not implementation bugs:
  - BUG-3 (Critical, DEFERRED): Chat handler JWT protection -- explicitly "Offen" in progress table
  - BUG-4 (High, DEFERRED): api.ts 401 interceptor -- depends on BUG-3
  - BUG-8 (Low, ACKNOWLEDGED): No token revocation -- Phase 1.5 design limitation
- **Security Audit:** All security findings from round 1 are resolved (BUG-6, BUG-7, BUG-9 fixed). Remaining security item (BUG-3 chat handler) is deferred scope.
- **Production Ready:** CONDITIONALLY YES -- The auth system (login, validate, logout, frontend protection) is complete and correct. The three remaining items are explicitly deferred scope (Chat-Handler JWT integration). The auth feature can be deployed independently; chat handler JWT enforcement should be tracked as a follow-up ticket.
- **Recommendation:** Deploy the auth system (alice-auth container, frontend, database migration). Create a follow-up ticket for Chat-Handler JWT integration (BUG-3 + BUG-4). After that follow-up is implemented, run `/qa` again to verify AC-6 and EC-2.

## Deployment

**Deployed:** 2026-02-28
**Environment:** Production (alice.happy-mining.de, via VPN)

### Deployed Components

| Component                      | Status              | Notes                                                                        |
| ------------------------------ | ------------------- | ---------------------------------------------------------------------------- |
| `alice-auth` FastAPI container | ✅ Running (healthy) | Port 8002, automation + backend networks                                     |
| DB Migration 007               | ✅ Applied           | password_hash, last_login_at, is_active, failed_login_attempts, locked_until |
| nginx `/api/auth/` routing     | ✅ Live              | Direkt zu `alice-auth:8002` (kein n8n-Proxy)                                 |
| Frontend                       | ✅ Deployed          | Build + deploy via `./scripts/deploy-frontend.sh`                            |
| Initial passwords              | ✅ Gesetzt           | `./scripts/set-initial-passwords.sh` ausgeführt                              |
| Login verified                 | ✅ Bestätigt         | Login mit echten Credentials getestet und funktionsfähig                     |
| Chat-Handler JWT protection    | ⬜ Deferred          | Follow-up ticket: BUG-3 + BUG-4                                              |

### Production Verification
- alice-auth health: `curl https://alice.happy-mining.de/api/auth/health`
- Container status: `docker ps --filter name=alice-auth`
