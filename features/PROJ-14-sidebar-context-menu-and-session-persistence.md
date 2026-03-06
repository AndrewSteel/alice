# PROJ-14: Sidebar Context-Menu & Backend Session API

## Status: Planned
**Created:** 2026-03-06
**Last Updated:** 2026-03-06

## Dependencies
- Requires: PROJ-12 (Chat-Session Rename) — Rename-Infrastruktur (ChatListItem inline-edit) ist vorhanden
- Requires: PROJ-7 (JWT Auth) — JWT-Validierung für neue API-Endpunkte

---

## Übersicht

Drei zusammenhängende Verbesserungen, die gemeinsam ein architektonisch sauberes Session-Management ergeben:

1. **Context-Menu (Three-Dots Button):** Die aktuellen Inline-Icons (Stift + Mülleimer), die beim Hover erscheinen, werden durch einen einzelnen `⋯`-Button ersetzt. Ein Klick öffnet ein Dropdown-Menü mit „Umbenennen" (Pencil) und „Löschen" (Trash2), wobei Löschen einen Bestätigungs-Dialog erfordert.

2. **Backend Session API (n8n):** Neuer n8n-Workflow `alice-session-api` mit vier JWT-geschützten Endpunkten zum Auflisten, Abrufen, Umbenennen und Löschen von Sessions. PostgreSQL (`alice.sessions` + `alice.messages`) ist die Single Source of Truth.

3. **Frontend-Migration:** `useChatSessions.ts` wird von localStorage auf die neue Backend-API umgestellt. Sessions und Nachrichten werden vom Server geladen — geräteübergreifend, reload-sicher, vollständig im Multi-Tier-Memory-Ansatz verankert.

### Architektonische Einordnung

```
VORHER (PROJ-12 Zustand):
  Frontend RAM       ← Nachrichten (flüchtig, verloren nach Reload)
  localStorage       ← Session-Metadaten (gerätegebunden)
  alice.messages     ← Nachrichten (n8n schreibt, Frontend liest NIE)
  alice.sessions     ← Session-Metadaten (n8n schreibt, Frontend liest NIE)

NACHHER (PROJ-14 Ziel):
  alice.messages     ← Nachrichten (Source of Truth, Tier 1 Working Memory)
  alice.sessions     ← Session-Metadaten inkl. Titel (Source of Truth)
  Frontend RAM       ← Nachrichten (Cache, aus API geladen)
  localStorage       ← Nur noch JWT-Token (unverändertes auth.ts)
```

---

## User Stories

### A) Context-Menu
1. **Als Nutzer** möchte ich beim Überfahren eines Sidebar-Eintrags einen `⋯`-Button sehen, damit ich Aktionen kompakt aufrufen kann.
2. **Als Nutzer** möchte ich im Dropdown-Menü „Umbenennen" und „Löschen" mit passendem Icon wählen können, damit ich die Aktion sofort erkenne.
3. **Als Nutzer** möchte ich beim Klick auf „Löschen" einen Bestätigungs-Dialog sehen, bevor der Chat gelöscht wird, damit ich versehentliches Löschen verhindern kann.
4. **Als Nutzer** möchte ich das Menü durch Klick außerhalb oder Escape schließen, damit ich versehentlich geöffnete Menüs schnell loswerden kann.

### B) Backend Session API
5. **Als Nutzer** möchte ich meine Chat-Sessions nach einem Page-Reload noch sehen, damit ich nicht jedes Mal von vorne anfangen muss.
6. **Als Nutzer** möchte ich auf jeden Chat in der Sidebar klicken und dessen Verlauf im Chatfenster sehen — unabhängig von der Datumsgruppe.
7. **Als Nutzer** möchte ich meine Chats von verschiedenen Geräten aus sehen, damit ich nicht an einen Browser gebunden bin.
8. **Als Nutzer** möchte ich beim Umbenennen eines Chats, dass der neue Name auch nach einem Reload erhalten bleibt.
9. **Als Nutzer** möchte ich beim Löschen eines Chats, dass dieser auch aus dem Backend entfernt wird und nicht nur aus der Sidebar verschwindet.

### C) Session-Switching (alle Gruppen)
10. **Als Nutzer** möchte ich beim Klick auf eine leere neue Session eine passende Leerstate-Anzeige sehen, damit ich weiß, dass der Chat bereit ist.

---

## Acceptance Criteria

### A) Three-Dots Context-Menu

- [ ] AC-A1: Die bestehenden Inline-Buttons (Pencil + Trash2) in `ChatListItem.tsx` werden entfernt
- [ ] AC-A2: Beim Hover erscheint am rechten Rand ein Button mit `MoreHorizontal`-Icon (lucide-react)
- [ ] AC-A3: Klick auf `⋯` öffnet ein shadcn `DropdownMenu`
- [ ] AC-A4: Das Dropdown enthält zwei Einträge: „Umbenennen" (Pencil-Icon) und „Löschen" (Trash2-Icon)
- [ ] AC-A5: Klick „Umbenennen" → `isRenaming=true` (bestehender Inline-Edit-Modus unverändert)
- [ ] AC-A6: Klick „Löschen" → öffnet shadcn `AlertDialog` mit „Chat löschen?" + „Abbrechen" / „Löschen"
- [ ] AC-A7: Erst nach Bestätigung im AlertDialog wird `onDelete(session.id)` aufgerufen
- [ ] AC-A8: Dropdown schließt sich bei Klick außerhalb, Escape und nach jeder Auswahl
- [ ] AC-A9: Klick auf `⋯` löst **kein** `onSelect` aus (`e.stopPropagation()`)
- [ ] AC-A10: `⋯`-Button hat `aria-label="Optionen"`

### B) Backend Session API (n8n Workflow `alice-session-api`)

- [ ] AC-B1: `GET /webhook/alice/sessions` — gibt alle Sessions des authentifizierten Users zurück (`session_id`, `title`, `started_at`, `last_activity`), sortiert nach `last_activity DESC`
- [ ] AC-B2: `GET /webhook/alice/sessions/:id/messages` — gibt alle Nachrichten einer Session zurück (`role`, `content`, `timestamp`), sortiert nach `timestamp ASC`; gibt 403 zurück wenn Session nicht dem User gehört
- [ ] AC-B3: `PATCH /webhook/alice/sessions/:id` — nimmt `{"title": "neuer Titel"}` entgegen und aktualisiert `alice.sessions.title`; gibt 403 wenn nicht Eigentümer
- [ ] AC-B4: `DELETE /webhook/alice/sessions/:id` — löscht Session aus `alice.sessions` und alle zugehörigen Nachrichten aus `alice.messages`; gibt 403 wenn nicht Eigentümer
- [ ] AC-B5: Alle vier Endpunkte validieren den JWT (via Sub-Workflow-Call oder eingebettete Validierung) und geben 401 zurück bei fehlendem/ungültigem Token
- [ ] AC-B6: DB-Migration: `ALTER TABLE alice.sessions ADD COLUMN IF NOT EXISTS title VARCHAR(255);`
- [ ] AC-B7: Der `alice-chat-handler` schreibt den Session-Titel bei der ersten Nachricht in `alice.sessions.title` (analog zur bisherigen localStorage-Logik im Frontend)
- [ ] AC-B8: Der `alice-chat-handler` legt bei jeder neuen `session_id` einen Eintrag in `alice.sessions` an (UPSERT), falls noch nicht vorhanden

### C) Frontend-Migration (`useChatSessions.ts`)

- [ ] AC-C1: Beim App-Start werden Sessions via `GET /webhook/alice/sessions` geladen (nicht mehr aus localStorage)
- [ ] AC-C2: Beim Klick auf eine Session werden die Nachrichten via `GET /webhook/alice/sessions/:id/messages` geladen, sofern noch nicht im RAM-Cache vorhanden
- [ ] AC-C3: `renameSession()` sendet `PATCH /webhook/alice/sessions/:id` und aktualisiert den RAM-State nach Erfolg
- [ ] AC-C4: `deleteSession()` sendet `DELETE /webhook/alice/sessions/:id` und entfernt die Session aus dem RAM-State nach Erfolg
- [ ] AC-C5: Neue Sessions werden weiterhin via `createNewSession()` lokal erstellt und erst nach dem ersten gesendeten Chat-Text im Backend sichtbar (kein Vorab-`POST`)
- [ ] AC-C6: Nachrichten einer Session werden beim ersten Abruf gecacht (RAM) und nicht erneut vom Backend geladen solange die Session aktiv ist
- [ ] AC-C7: Beim Löschen einer aktiven Session wird automatisch eine neue leere Session erstellt und aktiv geschaltet (Verhalten unverändert)
- [ ] AC-C8: Der `alice_sessions` localStorage-Key wird beim App-Start migriert: vorhandene Session-IDs werden ignoriert (Backend ist Source of Truth); der Key wird gelöscht
- [ ] AC-C9: Während Sessions geladen werden, zeigt die Sidebar einen Lade-Indikator (Skeleton oder Spinner)
- [ ] AC-C10: Das Chatfenster zeigt für Sessions ohne Nachrichten eine Leerstate-Ansicht

---

## Edge Cases

- **Neue Session vor dem ersten Chat:** Session existiert noch nicht im Backend. Erst nach `sendMessage()` legt der `alice-chat-handler` den Eintrag in `alice.sessions` an. Das Frontend zeigt die neue Session lokal in der Sidebar bis zum nächsten Reload.
- **Session-ID-Kollision (unwahrscheinlich):** UUIDs sind kollisionsresistent. Kein besonderer Fallback nötig.
- **Backend nicht erreichbar beim Laden:** `GET /webhook/alice/sessions` schlägt fehl → Fehlermeldung in der Sidebar; bestehende Sessions im RAM-State bleiben sichtbar (kein Datenverlust für laufende Session).
- **Parallele Tabs:** Kein Cross-Tab-Sync in Phase 1. Tab A und Tab B können unterschiedliche RAM-States haben. Beim nächsten Reload sieht beide Tabs denselben Backend-Zustand.
- **Löschen im anderen Tab:** Session wird im Backend gelöscht, im anderen Tab noch sichtbar bis Reload. Wenn die alte Session angesteuert wird, gibt `/messages` 403 → leere Ansicht, kein Crash.
- **Bestätigung beim Löschen der aktiven Session:** Identisches Verhalten wie bisher: neue leere Session wird erstellt.
- **Sehr langer Nachrichtenverlauf:** Der Abruf via `/messages` gibt alle Nachrichten der Session zurück. Bei sehr langen Sessions (>200 Nachrichten) kann die Antwort groß werden — im Frontend wird alles gerendert (kein Paging in Phase 1; Paging ist ein PROJ-15-Thema).
- **Migration bestehender localStorage-Sessions:** Der Nutzer hat u.U. Sessions in localStorage, die im Backend bereits in `alice.messages` existieren (mit korrekter `session_id`). Diese sind über die Backend-API sofort verfügbar; localStorage wird ignoriert und gelöscht.

---

## Technical Requirements

### Frontend
- **shadcn/ui:** `DropdownMenu` und `AlertDialog` (nachinstallieren falls nötig: `npx shadcn@latest add dropdown-menu alert-dialog`)
- **lucide-react:** `MoreHorizontal` (neu), `Pencil`, `Trash2` (bereits vorhanden)
- **Kein neues npm-Paket**

### Backend (n8n)
- **Neuer Workflow:** `alice-session-api` mit Webhook-Trigger für vier Routen
- **Datenbankzugriff:** PostgreSQL Credential `pg-alice` (ID: `2YBtxcocRMLQuAdF`)
- **JWT-Validierung:** Sub-Workflow-Call zur bestehenden Auth-Validierung oder eingebettetes JWT-Decode
- **Keine neuen Docker-Container**

### Datenbank
- **Migration:** `alice.sessions.title VARCHAR(255)` (additive, kein Breaking Change)
- **Bestehende Indizes** bleiben unverändert

### nginx
- **Neue Location:** `/api/webhook/alice/` → n8n (analog zu `/api/webhook/`) mit JWT-Anforderung; Rate-Limit-Zone `chat_limit` greift dort nicht (Sessions sind kein LLM-Call)

---

<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-14 besteht aus vier klar abgegrenzten Bausteinen, die alle zusammenpassen müssen:

| Baustein | Was wird gebaut | Wo |
|---|---|---|
| A | Context-Menu (⋯-Button) in der Sidebar | Frontend: `ChatListItem.tsx` |
| B | Session-API (4 Endpunkte) | Backend: n8n Workflow `alice-session-api` |
| C | Hook-Migration (localStorage → API) | Frontend: `useChatSessions.ts` + `services/api.ts` |
| D | nginx-Route für Session-API | Infra: `nginx/conf.d/alice.conf` |
| E | DB-Migration (title-Spalte) | PostgreSQL: `alice.sessions` |
| F | Chat-Handler UPSERT | Backend: `alice-chat-handler` (bestehender Workflow) |

---

### A) Komponentenstruktur (Baustein A)

```
ChatListItem (ChatListItem.tsx — modifiziert)
├── [Rename-Modus] Input  ← unverändert (PROJ-12)
└── [Normal-Modus]
    ├── <span> Titel (truncated)
    └── [on hover] MoreHorizontal-Button (⋯)
        └── shadcn DropdownMenu
            ├── MenuItem: Pencil + "Umbenennen"
            │     → setzt isRenaming = true (bestehende Logik)
            └── MenuItem: Trash2 + "Löschen" (rot)
                  → öffnet AlertDialog
                      ├── "Abbrechen" → close
                      └── "Löschen" (destructive) → ruft onDelete() auf
```

**Bereits installierte shadcn-Komponenten (kein `npm install` nötig):**
- `dropdown-menu` ✅
- `alert-dialog` ✅
- `skeleton` ✅ (für Lade-Indikator in der Sidebar)

---

### B) Backend-Architektur: n8n Workflow `alice-session-api`

Neuer Workflow mit **vier Webhook-Nodes**, je einer pro Endpunkt. Alle vier teilen denselben JWT-Validierungsblock (Sub-Workflow-Call zur bestehenden `alice-auth-validate`-Logik).

```
Webhook (GET /alice/sessions)
  → JWT-Validierung (Sub-Workflow)
  → PostgreSQL: SELECT sessions WHERE user_id = $uid ORDER BY last_activity DESC
  → Respond to Webhook (JSON array)

Webhook (GET /alice/sessions/:id/messages)
  → JWT-Validierung
  → PostgreSQL: SELECT + Ownership-Check (403 wenn fremd)
  → PostgreSQL: SELECT messages WHERE session_id = $id ORDER BY timestamp ASC
  → Respond to Webhook (JSON array)

Webhook (PATCH /alice/sessions/:id)
  → JWT-Validierung
  → PostgreSQL: Ownership-Check (403 wenn fremd)
  → PostgreSQL: UPDATE sessions SET title = $title
  → Respond to Webhook (200 OK)

Webhook (DELETE /alice/sessions/:id)
  → JWT-Validierung
  → PostgreSQL: Ownership-Check (403 wenn fremd)
  → PostgreSQL: DELETE sessions (ON DELETE CASCADE löscht messages mit)
  → Respond to Webhook (204 No Content)
```

**Datenbankzugriff:** Credential `pg-alice` (ID: `2YBtxcocRMLQuAdF`)
**Dateipfad:** `workflows/core/alice-session-api.json`

---

### C) Datenfluss nach der Migration (Baustein C)

```
App-Start:
  useChatSessions.init()
  → GET /api/webhook/alice/sessions (Bearer JWT)
  → RAM: sessions[] befüllt, Sidebar rendert
  → localStorage "alice_sessions" wird gelöscht (einmalige Migration)

Session-Klick (noch nicht gecacht):
  → GET /api/webhook/alice/sessions/:id/messages
  → RAM-Cache: messagesBySession[id] = [...]
  → Chatfenster rendert Verlauf

Session-Klick (bereits gecacht):
  → Direkt aus RAM — kein API-Call

Umbenennen:
  → PATCH /api/webhook/alice/sessions/:id
  → Bei Erfolg: RAM-State aktualisiert (optimistisch)

Löschen (nach AlertDialog-Bestätigung):
  → DELETE /api/webhook/alice/sessions/:id
  → Bei Erfolg: RAM-State bereinigt
  → Falls aktive Session: neue leere Session erstellt (Verhalten unverändert)

Neue Nachricht (erste in neuer Session):
  → alice-chat-handler empfängt Nachricht
  → UPSERT alice.sessions (session_id, user_id, title = erste 40 Zeichen)
  → Session ist erst danach im Backend sichtbar (AC-C5: kein Vorab-POST)
```

**Neues `sessionsLoading`-State:**
- `true` während des initialen API-Calls
- Sidebar rendert `Skeleton`-Komponenten (3 Platzhalter)
- `false` sobald API antwortet (Erfolg oder Fehler)

---

### D) nginx-Route (Baustein D)

Eine neue `location`-Block für `/api/webhook/alice/` wird **vor** dem bestehenden `/api/webhook/`-Block eingefügt. Der Unterschied: **kein `chat_limit` Rate-Limit** (Sessions sind kein LLM-Call).

```
nginx-Routing (Priorität: oben = höher):
  /api/webhook/alice/   → n8n (kein Rate-Limit, nur CORS + Security-Headers)
  /api/webhook/         → n8n (chat_limit Rate-Limit bleibt erhalten)
```

---

### E) Datenbankschema (Baustein E)

```
alice.sessions (bestehend + Erweiterung):
  session_id   UUID  PRIMARY KEY       ← bleibt
  user_id      INT   FK alice.users    ← bleibt
  started_at   TIMESTAMPTZ             ← bleibt
  last_activity TIMESTAMPTZ            ← bleibt
  title        VARCHAR(255)  NEW       ← additive Migration, kein Breaking Change

alice.messages (unverändert):
  message_id   SERIAL  PRIMARY KEY
  session_id   UUID    FK alice.sessions ON DELETE CASCADE  ← löscht mit
  role         TEXT
  content      TEXT
  timestamp    TIMESTAMPTZ
```

**Migration:** `ALTER TABLE alice.sessions ADD COLUMN IF NOT EXISTS title VARCHAR(255);`
Idempotent, kann jederzeit ausgeführt werden. Bestehende Zeilen erhalten `NULL` als title — kein Problem, da der Chat-Handler beim nächsten Aufruf einen Titel schreibt.

---

### F) Chat-Handler-Update (Baustein F)

Im bestehenden `alice-chat-handler`-Workflow wird ein UPSERT-Schritt ergänzt:

```
Beim Empfang einer Nachricht:
  1. JWT validieren (unverändert)
  2. UPSERT alice.sessions:
       ON CONFLICT (session_id) DO UPDATE SET
         last_activity = NOW(),
         title = COALESCE(sessions.title, $firstMessageSlice)
  3. INSERT alice.messages (unverändert)
  4. Ollama-Call (unverändert)
  5. INSERT Antwort in alice.messages (unverändert)
```

`COALESCE` stellt sicher, dass ein manuell umbenannter Titel nicht überschrieben wird.

---

### Tech-Entscheidungen (Begründung)

| Entscheidung | Warum |
|---|---|
| 4 separate Webhook-Nodes statt 1 + Switch | Klarer, einfacher zu debuggen; n8n-Webhook-URL-Parameter (`:id`) sind pro Node konfigurierbar |
| RAM-Cache statt sessionStorage | Kein zusätzlicher Speicher; Session-Daten sind sowieso flüchtig zwischen Tabs |
| Kein Vorab-POST für neue Sessions | Vermeidet leere Sessions im Backend; Backend erfährt erst von der Session wenn tatsächlich eine Nachricht gesendet wird |
| ON DELETE CASCADE in DB | Verhindert Waisen-Nachrichten; kein manuelles Delete der messages nötig |
| nginx-Location vor chat_limit | Session-API-Calls sind schnelle DB-Queries, kein Grund für LLM-Throttling |

---

### Keine neuen npm-Pakete

Alle benötigten shadcn-Komponenten (`dropdown-menu`, `alert-dialog`, `skeleton`) sind bereits installiert. `MoreHorizontal` ist in `lucide-react` enthalten.

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
