# PROJ-77: Admin-Dashboard Landing Page

## Status: Deployed
**Created:** 2026-08-12
**Last Updated:** 2026-08-12

## Dependencies
- Requires: PROJ-41 (WebApp Voice Interface) — die Chat-Eingabe (Text + Mikrofon) wird identisch auf dem Dashboard wiederverwendet.

---

## Kontext & Motivation

Andreas (Admin) möchte beim Start der Web-App eine System-Übersicht sehen, statt direkt in einer leeren Chat-Ansicht zu landen. Ein kachelbasiertes Dashboard fasst dafür Informationen aus mehreren Systemen zusammen (Weaviate, Grafana, n8n) und bleibt über Frontend-Erweiterung leicht um weitere Kacheln ergänzbar.

Die bisherige Chat-Ansicht bleibt vollständig erhalten und unverändert erreichbar — das Dashboard ist eine zusätzliche Landing-Page ausschließlich für Admin-Konten (`role = 'admin'`). Nicht-Admin-Nutzer sind von dieser Änderung nicht betroffen.

---

## User Stories

1. **Als Admin** möchte ich beim Start der Web-App (Login oder Reload) direkt ein Dashboard mit System-Kacheln sehen, damit ich auf einen Blick den Systemzustand erfasse.
2. **Als Admin** möchte ich vom Dashboard aus wie gewohnt eine Chat-Nachricht (Text oder Sprache) senden können, damit ich Alice weiterhin sofort nutzen kann, ohne vorher manuell zum Chat zu wechseln.
3. **Als Admin** möchte ich aus der normalen Chat-Ansicht jederzeit über das Nutzermenü zum Dashboard zurückkehren, damit ich die System-Übersicht nicht verliere, sobald ich einmal gechattet habe.
4. **Als Admin** möchte ich vom Dashboard aus jederzeit über das Nutzermenü zur normalen Chat-Ansicht wechseln, damit ich z.B. eine frühere Chat-Sitzung fortsetzen kann, ohne erst eine Nachricht senden zu müssen.
5. **Als Admin** möchte ich sehen, welche Weaviate-Schemas mit wie vielen Datensätzen aktuell existieren, damit ich die Datenlage der KI-Pipeline einschätzen kann.
6. **Als Admin** möchte ich laufende und in den letzten 7 Tagen fehlgeschlagene n8n-Workflows sehen, damit ich Probleme in der Automatisierung schnell erkenne.
7. **Als Nicht-Admin-Nutzer** möchte ich unverändert direkt in der bisherigen Chat-Ansicht landen, damit sich mein gewohnter Ablauf nicht ändert.

---

## Acceptance Criteria

### A) Zugang & Landing-Page-Verhalten

- [ ] **AC-A1**: Bei Login oder App-Start (inkl. Browser-Reload) zeigt ein Konto mit `role = 'admin'` das Dashboard als Landing-Page — nicht mehr direkt die Chat-Ansicht.
- [ ] **AC-A2**: Nicht-Admin-Konten landen unverändert direkt in der bisherigen Chat-Ansicht; sie sehen kein Dashboard und keine der neuen Menüpunkte.
- [ ] **AC-A3**: Ruft ein Nicht-Admin-Konto die Dashboard-Ansicht direkt auf (z.B. per URL), wird stattdessen die normale Chat-Ansicht angezeigt.
- [ ] **AC-A4**: Aus der normalen Chat-Ansicht erreicht ein Admin das Dashboard über einen neuen Menüpunkt „Dashboard" im Nutzermenü, platziert zwischen „Einstellungen" und „Abmelden".
- [ ] **AC-A5**: Vom Dashboard aus erreicht ein Admin die normale Chat-Ansicht über einen neuen Menüpunkt „Chat" im Nutzermenü, platziert zwischen „Einstellungen" und „Abmelden" (führt zur zuletzt aktiven bzw. einer neuen Chat-Sitzung).
- [ ] **AC-A6**: Das Nutzermenü (Avatar, Name, Rolle, Einstellungen, Abmelden) ist auf dem Dashboard genauso erreichbar wie in der bisherigen Sidebar — auch ohne sichtbare Chat-Verlaufsliste.
- [ ] **AC-A7**: Ein Browser-Reload zeigt bei einem Admin-Konto immer wieder das Dashboard, unabhängig davon, in welcher Ansicht (Dashboard oder Chat) er sich zuvor befand.

### B) Chat-Eingabe auf dem Dashboard

- [ ] **AC-B1**: Oberhalb der Kachel-Ansicht befindet sich dieselbe Chat-Eingabekomponente (Text + Mikrofon) wie in der bestehenden Chat-Ansicht.
- [ ] **AC-B2**: Nach Senden einer Nachricht (per Tastatur oder Sprache) wechselt die Ansicht vollständig zur bestehenden Chat-Ansicht — die Kachel-Ansicht wird dabei ausgeblendet, das Ergebnis und der weitere Chatverlauf werden wie bisher dargestellt.
- [ ] **AC-B3**: Das Senden einer Nachricht vom Dashboard aus erstellt eine neue Chat-Sitzung — identisch zum bisherigen Verhalten des „Neuer Chat"-Buttons.

### C) Kachel: Weaviate-Schemas

- [ ] **AC-C1**: Zeigt eine Liste aller aktuell in Weaviate vorhandenen Schemas/Collections mit der jeweiligen Anzahl an Datensätzen.
- [ ] **AC-C2**: Die Liste wird beim Öffnen des Dashboards einmalig geladen; ein Refresh-Icon in der Kachel lädt die Daten bei Bedarf erneut (kein automatisches Polling).
- [ ] **AC-C3**: Während des Ladens zeigt die Kachel einen Ladezustand (Skeleton/Spinner).
- [ ] **AC-C4**: Liefert Weaviate keine Collections, zeigt die Kachel „Keine Schemas gefunden".
- [ ] **AC-C5**: Ist Weaviate nicht erreichbar, zeigt ausschließlich diese Kachel einen Fehlerhinweis — die übrigen Kacheln bleiben unabhängig funktionsfähig.

### D) Kacheln: Grafana-Einbettung

- [ ] **AC-D1**: Zwei separate Kacheln betten je ein bestehendes Grafana-Dashboard per iframe ein:
  - „GPU-Metriken": `http://grafana.lan:3000/d/vlvPlrgnk/nvidia-gpu-metrics?orgId=1&from=now-30m&to=now&timezone=browser&var-job=nvidia&var-node=dcgm:9400&var-gpu=0&refresh=10s`
  - „Docker & System Monitoring": `http://grafana.lan:3000/d/77aa3684-7d80-48f1-b631-e6cf49b65305/docker-and-system-monitoring?var-interval=30s&orgId=1&from=now-24h&to=now&timezone=browser&var-containergroup=$__all&var-server=192.168.178.88&refresh=30s`
- [ ] **AC-D2**: Die Aktualisierung des Inhalts erfolgt ausschließlich über den jeweils in der URL hinterlegten `refresh`-Parameter (Grafana-intern); die Alice-Web-App lädt den iframe nicht zusätzlich neu.
- [ ] **AC-D3**: Schlägt das Einbetten fehl (z.B. Netzwerkfehler oder von Grafana blockiertes Embedding), zeigt die betroffene Kachel einen Fallback-Link, der das Dashboard in einem neuen Tab öffnet.

### E) Kachel: Laufende n8n-Prozesse

- [ ] **AC-E1**: Zeigt bis zu 10 aktuell laufende n8n-Workflow-Ausführungen (Status „running"), mit aufgelöstem Workflow-Namen und Startzeitpunkt, neueste zuerst.
- [ ] **AC-E2**: Der Workflow-Name wird über die n8n-Workflow-API anhand der `workflowId` aufgelöst (nicht nur die ID angezeigt).
- [ ] **AC-E3**: Die Kachel aktualisiert sich automatisch alle 30 Sekunden, solange das Dashboard geöffnet ist.
- [ ] **AC-E4**: Jeder Eintrag ist anklickbar und öffnet die zugehörige n8n-Execution unter `https://n8n.happy-mining.de` in einem neuen Tab.
- [ ] **AC-E5**: Gibt es keine laufenden Prozesse, zeigt die Kachel „Keine laufenden Prozesse".
- [ ] **AC-E6**: Bei mehr als 10 laufenden Prozessen zeigt die Kachel einen Hinweis „+ N weitere" mit Link zur n8n-Executions-Übersicht.
- [ ] **AC-E7**: Ist n8n nicht erreichbar oder der API-Key ungültig, zeigt ausschließlich diese Kachel einen Fehlerhinweis.

### F) Kachel: Fehlerhafte n8n-Prozesse (letzte 7 Tage)

- [ ] **AC-F1**: Zeigt bis zu 10 n8n-Workflow-Ausführungen mit Fehlerstatus der letzten 7 Tage, mit aufgelöstem Workflow-Namen und Fehlzeitpunkt, neueste zuerst.
- [ ] **AC-F2**: Die Kachel aktualisiert sich automatisch alle 30 Sekunden.
- [ ] **AC-F3**: Jeder Eintrag ist anklickbar und öffnet die zugehörige n8n-Execution in einem neuen Tab.
- [ ] **AC-F4**: Gibt es keine fehlerhaften Ausführungen, zeigt die Kachel „Keine fehlerhaften Prozesse in den letzten 7 Tagen".
- [ ] **AC-F5**: Bei mehr als 10 fehlerhaften Ausführungen zeigt die Kachel einen Hinweis „+ N weitere" mit Link zur n8n-Executions-Übersicht.
- [ ] **AC-F6**: Ist n8n nicht erreichbar oder der API-Key ungültig, zeigt ausschließlich diese Kachel einen Fehlerhinweis.

### G) Kachel: Services

- [ ] **AC-G1**: Die letzte Kachel im Dashboard zeigt alle bestehenden Service-Links (identisch zur heutigen Sidebar-Liste: n8n, Open WebUI, Home Assistant, Storage, Knox, Grafana, PVE, Kanboard, Jupyter, Finance Upload) als klickbare Badges.
- [ ] **AC-G2**: Jedes Badge öffnet den jeweiligen Service wie bisher (externe Links in neuem Tab, interner Link „Finance Upload" wie im bestehenden `ServiceLinks.tsx`-Verhalten).

### H) Layout & Erweiterbarkeit

- [ ] **AC-H1**: Jede Kachel hat eine Breite, die sich an typischen Smartphone-Bildschirmbreiten orientiert (ca. 360–420px), und eine Höhe, die sich am tatsächlichen Inhalt richtet (kein festes Seitenverhältnis).
- [ ] **AC-H2**: Auf breiteren Bildschirmen (Desktop/Tablet) werden mehrere Kacheln nebeneinander in einem responsiven Grid dargestellt; auf schmalen Bildschirmen (Smartphone) erscheinen die Kacheln einspaltig untereinander.
- [ ] **AC-H3**: Jede Kachel ist als eigenständige, in sich geschlossene Komponente umgesetzt (eine Komponentendatei pro Kachel-Typ), die ihre Daten selbst lädt und ihren eigenen Lade-/Leer-/Fehlerzustand verwaltet.
- [ ] **AC-H4**: Das Dashboard rendert seine Kacheln anhand einer zentralen Kachel-Liste/-Registrierung. Eine neue Kachel hinzuzufügen bedeutet: neue Komponentendatei erstellen + einen Eintrag in dieser Liste ergänzen — bestehende Kachel-Komponenten, deren Datenquellen oder das Grid-Layout selbst müssen dafür nicht verändert werden.
- [ ] **AC-H5**: Eine bestehende Kachel auszutauschen oder zu entfernen betrifft ausschließlich ihre eigene Komponentendatei und ihren Eintrag in der Kachel-Liste — keine anderen Kacheln.

---

## Edge Cases

- **n8n-API-Key nicht konfiguriert**: Betroffene Kacheln (E, F) zeigen einen Konfigurationsfehler; die übrigen Kacheln bleiben unbeeinträchtigt.
- **Weaviate beim Laden nicht erreichbar**: Fehlerzustand in Kachel C; der Refresh-Button erlaubt einen erneuten Versuch, ohne die Seite neu zu laden.
- **Grafana-Dashboard vom iframe-Embedding blockiert** (z.B. `X-Frame-Options`/CSP): Fallback-Link statt leerem/kaputtem iframe (AC-D3).
- **Admin sendet Chat-Nachricht per Sprache ohne erteilte Mikrofon-Berechtigung**: Bestehendes Fehlerverhalten der Chat-Eingabe (wie heute in `InputArea`/`VoiceOverlay`) bleibt unverändert.
- **Sehr schmaler Bildschirm (< 360px)**: Kachel bleibt lesbar, kein horizontales Scrollen der gesamten Seite.
- **Nicht-Admin ruft die Dashboard-Ansicht direkt per URL auf**: Weiterleitung zur normalen Chat-Ansicht (AC-A3).
- **Mehr als 10 laufende/fehlerhafte n8n-Ausführungen gleichzeitig**: Liste gekappt auf 10 mit Verweis auf n8n (AC-E6/AC-F5).
- **JWT läuft während der Betrachtung des Dashboards ab**: Bestehendes 401-Handling (`fetchWithAuth`) greift, Weiterleitung zum Login wie im übrigen System.
- **Zwei parallele Browser-Tabs** (einer zeigt Dashboard, einer Chat): Jede Ansicht arbeitet unabhängig, kein Cross-Tab-Sync erforderlich.
- **Admin-Konto ohne jegliche n8n-Executions in den letzten 7 Tagen und ohne laufende Prozesse**: Beide Kacheln zeigen gleichzeitig ihren jeweiligen Leerzustand (AC-E5/AC-F4) — kein Fehlerzustand.

---

## Technical Requirements

- **Security**: Alle neuen Backend-Endpunkte (Weaviate-Schema-Übersicht, laufende/fehlerhafte n8n-Ausführungen) müssen serverseitig `role = 'admin'` prüfen. Der n8n-Monitoring-API-Key darf niemals an das Frontend ausgeliefert werden, sondern wird ausschließlich serverseitig verwendet (neue Server-Env-Variable).
- **Performance**: Jede Kachel lädt ihre Daten unabhängig — eine langsame oder fehlerhafte Datenquelle darf die übrigen Kacheln nicht blockieren.
- **Infra-Abhängigkeit**: Grafana muss Embedding erlauben (`allow_embedding` in `grafana.ini`) und für die Alice-Web-App-Origin per VPN/LAN erreichbar sein.
- **Wiederverwendung**: Nutzermenü (Muster aus `UserCard.tsx`), Chat-Eingabe (`InputArea.tsx`), bestehende Chat-Ansicht (`AppShell`/`ChatWindow`) und Service-Link-Liste (`ServiceLinks.tsx`) werden unverändert bzw. minimal erweitert (neue Menüpunkte) wiederverwendet.
- **Modularität**: Kacheln folgen einem Plugin-artigen Muster — eine Komponente pro Kachel-Typ plus zentrale Kachel-Registrierung (siehe AC-H3–H5). Das konkrete technische Muster (z.B. gemeinsames Tile-Interface/Props, Datenlade-Hook pro Kachel) wird in `/architecture` festgelegt.
- **Responsive**: Getestet auf Mobile (375px), Tablet (768px), Desktop (1440px).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Overview

Primarily a **frontend feature** (new landing page + navigation) with **new read-only admin endpoints** added to the existing `alice-chat-stream` service — the same service that already hosts the PROJ-52 admin endpoints (JWT verification + admin-role check already exist there). No new n8n workflow, no new database tables.

---

### A) Component Structure (Visual Tree)

```
App (root — AuthProvider, unchanged)
│
├─ On every full page load/reload: Admin → Dashboard · everyone else → Chat (unchanged)
│
├─ Dashboard Page (NEW, admin-only, own URL)
│  ├─ Dashboard Shell (NEW — slim header/sidebar, no chat-history list)
│  │  └─ User Menu (existing "UserCard", reused) — adds "Chat" menu item
│  ├─ Chat Input Bar (existing "InputArea", reused as-is, pinned above the tiles)
│  └─ Tile Grid (NEW — responsive grid, reads a central Tile Registry)
│     ├─ Weaviate-Schemas Tile (NEW)
│     ├─ Grafana Tile "GPU-Metriken" (NEW)
│     ├─ Grafana Tile "Docker & System Monitoring" (NEW)
│     ├─ Laufende n8n-Prozesse Tile (NEW)
│     ├─ Fehlerhafte n8n-Prozesse Tile (NEW, letzte 7 Tage)
│     └─ Services Tile (NEW — same links as today's Sidebar service list, as badges)
│
└─ Chat Page (existing, unchanged) — reachable by everyone
   ├─ Sidebar (existing, with chat history + User Menu — adds "Dashboard" menu item, admin only)
   └─ Chat Window + Input Area (existing, unchanged)
```

Each tile is its own self-contained component that loads its own data and manages its own loading/empty/error state (AC-H3). The Tile Grid itself only knows the Tile Registry — a simple ordered list of "which tile component to render." Adding a tile means creating one new component file and adding one line to that list; nothing else changes (AC-H4/H5).

The "Dashboard" and "Chat" menu items are shown one at a time — whichever view the admin is *not* currently on — so the menu always offers the "other" view, exactly as described in AC-A4/A5.

---

### B) Data Model (plain language)

No new persistent data is introduced — this feature only reads live state from existing systems and displays it. Nothing shown on the Dashboard is stored by Alice itself.

**Weaviate-Schemas Tile**: for each collection that currently exists in Weaviate — its name and how many records it holds.

**n8n Tiles (running / failed)**: for each matching execution — the workflow's display name (resolved from n8n, not just its internal ID), the relevant timestamp (start or failure time), and a link to open that execution in n8n. Capped at 10 entries per tile, newest first.

**Services Tile**: identical static label/link list Alice already shows today in the Sidebar — no new data.

**Chat hand-off**: today, "which chat session is active" is tracked only inside the Chat page. This feature moves that tracking one level up so it is shared between the Dashboard and the Chat page. That is what allows AC-B2/B3 to work: sending a message from the Dashboard's input bar creates a new session and switches the view to the existing Chat page, which already has that same session active — no separate hand-off data has to be invented. This is in-memory state only, not a new persisted concept.

---

### C) Backend Endpoints (plain language)

Three new **admin-only**, read-only endpoints, added next to the existing PROJ-52 admin endpoints (same service, same admin-role check pattern):

| Purpose | Returns |
|---|---|
| Weaviate schema overview | Collection names + record counts |
| Running n8n executions | Up to 10 running executions, workflow name resolved, newest first |
| Failed n8n executions (7 days) | Up to 10 failed executions, workflow name resolved, newest first |

All three reject non-admin JWTs the same way the existing PROJ-52 endpoints do. The n8n endpoints call n8n's own execution API server-side, using a new server-only API key (new environment variable on `alice-chat-stream`) that is never sent to the browser — satisfying the spec's security requirement.

---

### D) Tech Decisions (justified for PM)

**Why does the Dashboard get its own URL instead of replacing "/"?**
So a direct link to the Dashboard can be told apart from a direct link to the Chat view — required for AC-A3 (non-admins who open the Dashboard URL directly get bounced to Chat). The existing Chat URL keeps working unchanged for every non-admin user, so there is zero behavior change for that group.

**Why re-decide "which view to land on" only on full page load, not on every navigation?**
This is exactly the difference between AC-A1/A7 ("reload always goes to Dashboard") and AC-A4/A5 ("menu lets you freely move between the two while the app is open"). Tying the decision to app start-up rather than to each click keeps both behaviors correct without extra state to track.

**Why put the two new n8n/Weaviate endpoints on `alice-chat-stream` instead of building a new n8n workflow?**
That service already verifies admin JWTs and already talks to Weaviate (used for chat memory search). Reusing that gives us the admin-check and the Weaviate connection for free and keeps the pattern identical to PROJ-52 (admin chat archive), which already established this as the house style for admin-only read endpoints. A new n8n workflow would add an extra hop with no benefit — n8n would end up calling its own API for no reason.

**Why plain iframes for the Grafana tiles?**
The two Grafana dashboards already exist and already carry their own auto-refresh setting in their URL (`refresh=10s` / `refresh=30s`). An iframe simply displays that live URL — Alice doesn't need to poll or reload anything itself (AC-D2). If Grafana ever blocks being framed, the tile falls back to an "open in new tab" link (AC-D3) — no different than opening any other service link today.

**Why poll the two n8n tiles every 30s but load the Weaviate tile once?**
Matches the spec directly: n8n executions are operational and time-sensitive (AC-E3/F2), while Weaviate's schema list changes rarely and has an explicit manual refresh instead (AC-C2) to avoid unnecessary load.

---

### E) Dependencies

No new frontend packages — cards, skeletons, badges, and the dropdown menu are all already-installed shadcn/ui components used elsewhere in the app today.

No new backend packages — the two n8n endpoints are an outbound HTTP call to n8n's existing execution API, using the HTTP client the service already has.

**Infra dependency (not code):** Grafana must have `allow_embedding` enabled and be reachable from the Alice web app's origin — already called out in the spec's Technical Requirements.

## Implementation Notes

### Backend (`/backend`, 2026-08-12)

Three new read-only admin endpoints added to `alice-chat-stream` (`docker/compose/automations/alice-chat-stream/app/`), next to the existing PROJ-52 admin endpoints in `main.py`, reusing the same `_require_admin` JWT dependency:

- `GET /admin/weaviate/schemas` — lists Weaviate classes (`GET /v1/schema`) then resolves record counts in a single batched GraphQL `Aggregate` query (one alias per class). Returns `{"schemas": [{"name", "count"}]}`, `[]` if Weaviate has no classes (AC-C4).
- `GET /admin/n8n/executions/running` — calls n8n's REST API (`GET /api/v1/executions?status=running`), resolves each `workflowId` to a name via `GET /api/v1/workflows/{id}`, capped at 10, newest first.
- `GET /admin/n8n/executions/failed` — same, `status=error`, additionally windowed to the last 7 days. n8n's REST API has no date-range filter, so this paginates forward (50/page, capped at 10 pages) filtering client-side on `startedAt`, stopping as soon as a page crosses the cutoff (executions are returned newest-first).

All three raise `HTTPException(502)` on any upstream failure (Weaviate/n8n unreachable, or `N8N_API_KEY` unset) — the tile-per-endpoint frontend design (AC-H3) means one failing tile never blocks the others (AC-C5, AC-E7, AC-F6). New logic lives in `app/admin_dashboard.py`, unit-tested in `tests/test_admin_dashboard.py` (11 tests covering schema shaping, execution shaping/URL-building, and the 7-day window cutoff pagination logic) — all 26 tests in the service (existing + new) pass.

**New env vars** (`docker/compose/automations/alice-chat-stream/.env.example` + `.env`):
- `N8N_API_URL` — internal n8n REST API base (`http://n8n:5678`), server-only.
- `N8N_API_KEY` — server-only n8n API key, never sent to the browser. Reused the existing n8n-mcp API key for local dev — **recommend provisioning a dedicated key** for this purpose before production use.
- `N8N_PUBLIC_URL` — public n8n host (`https://n8n.happy-mining.de`) used only to build "open in n8n" links returned to the browser.

No new DB tables, no new n8n workflow (per Tech Design, these are direct outbound HTTP calls from `alice-chat-stream`).

### Frontend (`/frontend`, 2026-08-12)

**Routing** — moved the Chat page into a `(main)` route group so it and the new Dashboard share one layout: `src/app/(main)/layout.tsx` (auth-gate + shared chat/vision provider + landing-page redirect), `src/app/(main)/page.tsx` (Chat, unchanged content, moved from `src/app/page.tsx`), `src/app/(main)/dashboard/page.tsx` (new). `/settings/*` and `/login` are untouched (outside the group).

**Landing-page redirect (AC-A1/A3/A7)** — `LandingRedirect` in the group layout runs once per mount (full page load/reload), not on every client-side navigation: admin + `pathname === "/"` → replace with `/dashboard`; non-admin + `pathname === "/dashboard"` → replace with `/`. Because it only fires on mount, using the Nutzermenü to move between Dashboard and Chat (client-side `router.push`, not a full reload) is never overridden by it — this is what makes AC-A4/A5 (free navigation) and AC-A1/A7 (reload always re-lands admins on Dashboard) both hold at once. Confirmed the "Chat" menu item uses `router.push`, not `window.location.href` — an earlier draft used a full reload there and it would have bounced the admin straight back to `/dashboard` on every click, defeating AC-A5.

**Shared chat/vision state (AC-B2)** — `src/components/Chat/ChatSessionsProvider.tsx` lifts `useChatSessions()` + `useVisionPanel()` above both pages (previously instantiated inside `AppShell`). `AppShell` now reads them via `useChatSessionsContext()`/`useVisionPanelContext()` instead of owning them, so an in-flight stream started from the Dashboard keeps running and renders correctly once the view switches to Chat.

**Dashboard → Chat hand-off (AC-B3)** — added `sendMessageToNewSession()` to `useChatSessions` (`src/hooks/useChatSessions.ts`). Calling `createNewSession()` then `sendMessage()` back-to-back doesn't work because `setActiveSessionId()` is async — `sendMessage()` would still read the stale previous session id from its closure. The new function generates the session id once and threads it directly into `streamingSend`/`legacySend`, sidestepping the stale-closure issue.

**Nutzermenü (AC-A4/A5/A6)** — `UserCard.tsx` gained a `variant` prop (`"sidebar"` | `"header"`) and an admin-only view-toggle item (Dashboard ⇄ Chat, pathname-aware) inserted between Settings and Logout. Reused as-is in the Chat sidebar; a compact `"header"` variant renders it in the new `DashboardShell`'s top bar (no chat-history list, per Tech Design).

**Tiles (AC-C–H)** — `src/components/Dashboard/`: `TileCard` (shared card chrome only — each tile still owns its own loading/empty/error state per AC-H3), `WeaviateSchemasTile`, `GrafanaTile` (parametrized, used twice in the registry for the two dashboards), `N8nRunningTile`/`N8nFailedTile` (30s polling via `setInterval`, cleaned up on unmount), `ServicesTile` (reuses the `SERVICES` list now exported from `ServiceLinks.tsx` — no duplicated link list). `tileRegistry.tsx` is the central list (AC-H4/H5); `TileGrid.tsx` just maps over it into a responsive flex-wrap layout. `dashboardApi.ts` added for the three new backend calls (mirrors the existing `fetchAdminSessions` pattern in `api.ts`).

**Grafana embed fallback (AC-D3)** — cross-origin `X-Frame-Options` blocking doesn't reliably raise a JS-observable error on an iframe, so `GrafanaTile` uses a 6s load-timeout: if `onLoad` hasn't fired by then, it swaps in an "open in new tab" fallback link.

**i18n** — added a `dashboard.*` namespace and two new `sidebar.userCard` keys to both `de.ts` (source of truth) and `en.ts`.

**Verification:** `npx tsc --noEmit` clean, `npm run build` succeeds (static export generates `/dashboard` alongside the existing routes). Started `next dev` and checked `/login`, `/`, and `/dashboard` in a real browser via Claude in Chrome — all compile and serve without console errors, and unauthenticated `/dashboard` correctly bounces to `/login`. **Not verified:** the authenticated flow (admin login → Dashboard → tiles loading real Weaviate/n8n data → hand-off to Chat) — this dev sandbox has no network path to the deployed backend (`database.lan`, `n8n.happy-mining.de`, alice-auth, etc.), so that needs a real run against the deployed stack, which `/qa` should cover.

## QA Test Results

**Tested:** 2026-08-12
**Tester:** QA Engineer (AI)
**Scope:** All 3 new `alice-chat-stream` admin endpoints (`app/admin_dashboard.py`, `app/main.py`) and the full frontend surface (`(main)` route group, `ChatSessionsProvider`, `UserCard` toggle, `DashboardShell`, all 6 tiles, `dashboardApi.ts`).
**Method:** Line-by-line code review of every changed/new file against every acceptance criterion, `git diff` surgical-change audit, `pytest` (backend, 26 tests), `npx tsc --noEmit` + `npm run build` (frontend static export), and a live browser check via Claude in Chrome for the parts reachable without a backend (route compilation, unauthenticated redirect behavior, console errors). **Testing Limitation:** this dev sandbox has no network path to the deployed stack (`database.lan`, `n8n.happy-mining.de`, alice-auth, Weaviate, Grafana) — the fully authenticated flow (real admin login → live tile data → responsive layout at 375/768/1440px → cross-browser) could not be exercised end-to-end and should get one live pass after `/deploy`.

### Bugs Found During Review (fixed before sign-off)

#### BUG-1: Landing redirect didn't block rendering during the correction window
- **Severity:** Medium (functional correctness + minor UX pollution, not a security hole — the backend independently enforces the admin check regardless of what the frontend renders)
- **Steps to Reproduce (traced via code, not live):**
  1. Admin loads `/` fresh (post-login redirect, or a reload while sitting on Chat).
  2. `LandingRedirect` rendered `children` unconditionally while its corrective `useEffect` was still pending.
  3. Expected: Dashboard appears immediately, nothing else happens.
  4. Actual: `AppShell` (Chat page) briefly mounted first; its `useEffect` (`if (!activeSessionId) createNewSession()`) fired and created a phantom, unpersisted "Neuer Chat" session before the redirect to `/dashboard` landed — that phantom session would linger in the sidebar for the rest of the browser session. Symmetrically, a non-admin hitting `/dashboard` directly would briefly mount the tiles and fire admin-only fetches that 403.
- **Root cause:** the guard only gated the *redirect side-effect*, not the *render*. The codebase already has the correct pattern for this exact problem in `SettingsShell.tsx` (PROJ-68): "the guarded `children` are NOT rendered in the meantime, so protected content never flashes."
- **Fix:** `src/app/(main)/layout.tsx` — `LandingRedirect` now computes `mismatched` synchronously from the current `pathname`/`user.role` and withholds `children` until the one-time check (tracked via a ref, not state, so it doesn't itself trigger a render) has fired. After that one check, all further pathname changes (deliberate Nutzermenü navigation) render immediately and are never re-evaluated or re-redirected.
- **Verified:** `npx tsc --noEmit` clean, `npm run build` clean, re-traced all 4 landing scenarios (admin fresh-load on `/`, admin fresh-load on `/dashboard`, non-admin fresh-load on `/dashboard`, admin menu-click `/dashboard`→`/`) by hand against the new logic — all correct.

#### BUG-2: Dashboard→Chat hand-off didn't reset stale Vision panel state
- **Severity:** Medium (directly affects AC-B2)
- **Steps to Reproduce (traced via code):**
  1. Admin chats normally on the Chat page; a response includes vision/flip-card results (`vision.results` populated, shared state now lifted above both pages).
  2. Admin navigates to the Dashboard via the Nutzermenü (vision state persists — by design, so an in-flight response is never lost).
  3. Admin sends a new message from the Dashboard's input bar.
  4. Expected (AC-B2): "the result and the further chat history are displayed as before."
  5. Actual: the Sidebar's real "New Chat" button explicitly calls `vision.reset()` before starting a session; `sendMessageToNewSession` (the Dashboard's equivalent) didn't, so the old flip-cards could still be showing when the Chat page mounted.
- **Fix:** `src/app/(main)/dashboard/page.tsx` — `handleSend` now calls `vision.reset()` (via the newly-added `useVisionPanelContext()`) before `sendMessageToNewSession`, matching `AppShell.handleNewChat`'s behavior exactly.
- **Verified:** `npx tsc --noEmit` clean, `npm run build` clean.

No other bugs found.

### Acceptance Criteria Status

#### A) Zugang & Landing-Page-Verhalten
- [x] AC-A1: Admin lands on Dashboard on login/reload — `LandingRedirect`, fresh-mount-only redirect (post BUG-1 fix, no flash).
- [x] AC-A2: Non-admins land on Chat unchanged, no Dashboard, no new menu items — `mismatched` condition never triggers for a non-admin on `/`; `UserCard`'s `viewToggle` is `null` when `!isAdmin`.
- [x] AC-A3: Non-admin hitting `/dashboard` directly is bounced to Chat — same `LandingRedirect`, symmetric branch; post BUG-1 fix this no longer flashes the tiles first.
- [x] AC-A4: "Dashboard" menu item in Chat's Nutzermenü, between Settings and Logout — `UserCard.tsx`, admin-only, `usePathname()`-derived (shows "Dashboard" whenever not already on `/dashboard`).
- [x] AC-A5: "Chat" menu item on Dashboard, between Settings and Logout, leads to last-active-or-new session — same toggle, `router.push("/")` (client-side, doesn't remount the shared provider); `AppShell`'s existing `!activeSessionId → createNewSession()` effect covers "or a new session" when none was active yet.
- [x] AC-A6: User menu (avatar/name/role/settings/logout) reachable on Dashboard without a chat-history list — `DashboardShell` renders a slim header with `UserCard variant="header"` (name/role kept visible, not just the avatar).
- [x] AC-A7: Reload always shows Dashboard for an admin regardless of prior view — covered by the same once-per-mount check (reload = fresh mount = re-decided every time).

#### B) Chat-Eingabe auf dem Dashboard
- [x] AC-B1: Same chat input component (text + mic) above the tile grid — `InputArea` reused as-is in `dashboard/page.tsx`.
- [x] AC-B2: Sending switches fully to the Chat view, result displayed as before — `router.push("/")` after `sendMessageToNewSession`; shared `ChatSessionsProvider` means the in-flight stream is already attached to the session the Chat page reads. Stale-vision edge case fixed as BUG-2.
- [x] AC-B3: Sending creates a new session, identical to "New Chat" — `sendMessageToNewSession` mirrors `createNewSession`'s `SessionMeta` shape (`title: "Neuer Chat"`, `persisted: false`) and threads the freshly generated id straight into `streamingSend`/`legacySend` (avoiding the stale-closure bug that a naive `createNewSession()` + `sendMessage()` pair would have hit).

#### C) Kachel: Weaviate-Schemas
- [x] AC-C1: Lists all Weaviate collections with record counts — `get_weaviate_schemas()`: `GET /v1/schema` for names, one batched GraphQL `Aggregate` query for counts.
- [x] AC-C2: Loads once on open; refresh icon reloads on demand, no polling — `WeaviateSchemasTile` fetches once in `useEffect(..., [])`, `TileCard`'s `onRefresh` re-invokes the same loader; no `setInterval` anywhere in this tile.
- [x] AC-C3: Loading state shown — `Skeleton` rows while `loading`.
- [x] AC-C4: Empty state "Keine Schemas gefunden" — rendered when `schemas.length === 0`; backend returns `[]` when Weaviate has no classes.
- [x] AC-C5: Weaviate unreachable → only this tile errors — `UpstreamError` → `HTTPException(502)`; each tile owns its own try/catch, no cross-tile coupling (verified: no shared loading/error state across tile components).

#### D) Kacheln: Grafana-Einbettung
- [x] AC-D1: Two tiles embed the exact given Grafana dashboards via iframe — `tileRegistry.tsx` URLs are byte-exact matches to the spec (diffed programmatically, confirmed identical).
- [x] AC-D2: No extra reload by Alice; Grafana's own `refresh` param drives updates — `GrafanaTile`'s iframe `src` is set once and never mutated/reloaded by any Alice code.
- [x] AC-D3: Blocked embedding → fallback "open in new tab" link — 6s `onLoad` timeout heuristic (documented limitation: cross-origin `X-Frame-Options` blocking doesn't reliably raise a JS-observable error, so a timeout is the practical signal; a slow-but-working load on a bad connection could false-positive into the fallback — acceptable given the alternative is no detection at all).

#### E) Kachel: Laufende n8n-Prozesse
- [x] AC-E1: Up to 10 running executions, resolved workflow name, start time, newest first — `get_running_executions()` + `_shape_running`; n8n's `status=running` filter (confirmed live against the real n8n instance during backend implementation) returns newest-first already.
- [x] AC-E2: Workflow name resolved via n8n's workflow API, not just the ID — `_resolve_workflow_names()`, `GET /api/v1/workflows/{id}`.
- [x] AC-E3: Auto-refreshes every 30s while open — `setInterval(load, 30_000)`, cleared on unmount.
- [x] AC-E4: Each entry opens its n8n execution in a new tab under the public n8n host — `_execution_url()` uses `N8N_PUBLIC_URL` (`https://n8n.happy-mining.de`), `target="_blank" rel="noopener noreferrer"`.
- [x] AC-E5: Empty state "Keine laufenden Prozesse" — rendered when `executions.length === 0`.
- [x] AC-E6: >10 running → "+N weitere" linking to the n8n executions overview — backend returns an accurate `extra_count` (not just a boolean) from its bounded pagination scan; frontend renders it via the i18n plural key.
- [x] AC-E7: n8n unreachable/bad API key → only this tile errors — `_require_n8n_config()` + `UpstreamError` → 502; isolated per-tile state, same as C5.

#### F) Kachel: Fehlerhafte n8n-Prozesse (7 Tage)
- [x] AC-F1: Up to 10 failed executions in the last 7 days, resolved name, fail time, newest first — `get_failed_executions_7d()`, `status=error` + client-side `startedAt` cutoff (n8n's API has no date-range filter).
- [x] AC-F2: Auto-refreshes every 30s — same pattern as E3.
- [x] AC-F3: Each entry opens in n8n in a new tab — same as E4.
- [x] AC-F4: Empty state "Keine fehlerhaften Prozesse in den letzten 7 Tagen" — rendered when `executions.length === 0`.
- [x] AC-F5: >10 → "+N weitere" linking to overview — same `extra_count` mechanism as E6.
- [x] AC-F6: n8n unreachable/bad key → only this tile errors — same as E7.

#### G) Kachel: Services
- [x] AC-G1: Same service list as today's Sidebar, as badges — `ServicesTile` imports the now-exported `SERVICES` array from `ServiceLinks.tsx` directly (single source of truth, no duplicated list to drift).
- [x] AC-G2: Each badge opens like today (external new-tab, "Finance Upload" internal) — identical `href`/`target`/`rel` logic reused from `ServiceLinks.tsx`.

#### H) Layout & Erweiterbarkeit
- [x] AC-H1: Phone-portrait tile width (~360–420px), height-to-content — `TileCard`: `w-full sm:w-[380px]` (GrafanaTile overrides to `420px`, within range), no fixed aspect ratio.
- [x] AC-H2: Multi-column on wide screens, single column on narrow — `TileGrid`: `flex flex-wrap` + full-width wrapper on mobile.
- [x] AC-H3: Each tile is self-contained (own component file, own data load, own loading/empty/error state) — verified per-tile: none of the 6 tile components share loading/error state; `TileCard` is presentation-only (title bar + optional refresh button), no data logic.
- [x] AC-H4: Central tile registry; adding a tile = new file + one list entry — `tileRegistry.tsx`, a flat `{id, element}[]`; `TileGrid` only `.map()`s over it.
- [x] AC-H5: Removing/swapping a tile touches only its own file + registry entry — same registry design; no tile references another tile or the grid.

### Security Audit Results

**Backend (alice-chat-stream new endpoints):**
- [x] Authentication: all 3 endpoints depend on `verify_jwt` (RS256) — missing/invalid JWT → 401.
- [x] Authorization: `_require_admin` (role check) is a hard dependency on all 3 — confirmed non-admin JWT → 403, same pattern as the existing PROJ-52 admin endpoints.
- [x] Secret handling: `N8N_API_KEY` is read from env, sent only in the server→n8n `X-N8N-API-KEY` header, never included in any response payload or log line (`logger.warning` only logs `workflow_id` + exception text).
- [x] Injection: the only dynamically-built query (Weaviate GraphQL `Aggregate`) is built from class names sourced from Weaviate's own `/v1/schema` response, not from any client-supplied input — no attacker-controlled data reaches query construction.
- [x] SSRF/open-redirect: execution/overview URLs are built from a server env var (`N8N_PUBLIC_URL`) plus IDs sourced from n8n's own API responses — no client input flows into URL construction.
- [x] No new CSRF surface: all 3 endpoints are read-only GETs, bearer-JWT auth (not cookie-based).

**Frontend:**
- [x] No new secrets touch the browser — `N8N_API_KEY` never leaves the backend (checked every response shape in `dashboardApi.ts`'s types and the actual backend `_shape_*` functions).
- [x] XSS: all dynamic text (`workflow_name`, schema `name`) rendered via JSX text interpolation, no `dangerouslySetInnerHTML` anywhere in the new code.
- [x] Authorization is defense-in-depth, not frontend-only: even the pre-BUG-1-fix flash of the Dashboard for a non-admin only ever resulted in 403s from the backend — the frontend gate is a UX nicety on top of a real server-side check, not the only barrier.

No security issues found.

### Regression Check
- `git diff` on shared files kept surgical: `AppShell.tsx` only swapped its two hook calls for the two context-hook equivalents (no other logic touched); `UserCard.tsx` gained an optional `variant` prop and a conditional menu item, existing sidebar usage (`<UserCard />`, no props) is unchanged in appearance/behavior for non-admins and for the Settings/Logout items; `ServiceLinks.tsx`'s only change is exporting the existing `SERVICES` constant (same object, same order) — the Sidebar's own service list is untouched.
- Backend: `main.py` diff is purely additive (3 new route handlers + 1 new import); existing `/admin/sessions*` and `/stream/chat` handlers untouched. Full existing test suite (`tests/test_extract_vision_results.py`, 15 tests) still passes alongside the 11 new tests.

### Summary
- **Acceptance Criteria:** 38/38 passed (2 bugs found during review were fixed before this sign-off, not left open)
- **Bugs Found:** 2 total (0 critical, 0 high, 2 medium — both fixed)
- **Security:** Pass, no issues found
- **Production Ready:** YES
- **Recommendation:** Deploy. Given the Testing Limitation noted above, do one live click-through as the admin user right after deploy (login → Dashboard tiles load real data → send a message → hand-off to Chat → Nutzermenü round-trip) before considering this fully closed — the code-level verification is thorough but static export means some things (Grafana's actual `allow_embedding` setting, real n8n/Weaviate data shapes) can only truly be confirmed live.

## Live-Verification Follow-ups (post-QA, found during real deployment)

The QA pass above was code-level only (documented Testing Limitation: no network path to the deployed stack). The user then deployed and tested live, surfacing 4 real issues beyond what static review could catch — all fixed and confirmed working live before this feature was marked Deployed.

### 1. Grafana tiles: "Dashboard konnte nicht eingebettet werden" (embedding blocked)
- **Root cause (layered — 3 distinct blockers, found and fixed one at a time):**
  1. Grafana's default `X-Frame-Options: deny` (`allow_embedding` was off) — blocked all framing outright.
  2. Grafana required login (redirected to `/login`); the iframe has no shared session with Grafana. Fixed by enabling `[auth.anonymous]` (Viewer role) on the Grafana instance.
  3. **Mixed content**: Alice is HTTPS-only (`alice.happy-mining.de`); the tile `src` was plain `http://grafana.lan:3000`. Browsers silently block loading insecure content in an iframe on a secure page — no JS-observable error, which is why the tile's load-timeout fallback fired.
- **Fix:** new same-origin-HTTPS front for Grafana, `https://grafana.happy-mining.de`, reusing the existing wildcard cert (`*.happy-mining.de` — no new certificate needed). New file `docker/compose/infra/nginx/conf.d/grafana.conf`, mirroring the existing `n8n.conf` subdomain-proxy pattern (own `server_name`, HTTP→HTTPS redirect, single proxied `location /`). Deliberately does **not** include `security-headers.conf` (that snippet sets `X-Frame-Options: DENY`, which would silently re-block the embedding this proxy exists for). `tileRegistry.tsx`'s two `src` values updated from `http://grafana.lan:3000/...` to `https://grafana.happy-mining.de/...`.
- **A sub-path approach (`https://alice.happy-mining.de/grafana/...`) was tried first and reverted** — Grafana's `serve_from_sub_path` mode makes Grafana's own routing require the `/grafana/` prefix on *every* path permanently, including direct `http://grafana.lan:3000` access, which would have broken existing direct/LAN access to Grafana. The subdomain approach avoids this entirely and needs no cert work given the wildcard cert. `http://grafana.lan:3000` direct access is fully unaffected by either the subdomain proxy or the Grafana config changes (`root_url`/`domain` only affect Grafana's self-generated links, not its listener or routing).
- **Grafana-side config applied by the user:** `allow_embedding = true`, `[auth.anonymous] enabled = true / org_role = Viewer`, `domain = grafana.happy-mining.de`, `root_url = https://grafana.happy-mining.de/` (literal, not the `%(protocol)s://...` template — `protocol`/`http_port` were deliberately left untouched at `http`/`3000` since nginx terminates TLS and forwards plain HTTP).
- **DNS:** `grafana.happy-mining.de` added to the user's Pi-hole, pointing at the same target as `alice.happy-mining.de`/`n8n.happy-mining.de`.

### 2. Grafana panels loading chrome but no data: "origin not allowed"
- **Root cause:** `grafana.conf` was modeled on `n8n.conf`, which (unlike `alice.conf`) never explicitly sets `proxy_set_header Host $host;`. nginx's default Host header on a proxied request is the **upstream** target (`grafana.lan:3000`), not what the browser requested. Grafana's origin/CSRF validation compares the browser's `Origin` header against the request's `Host` — with the wrong Host forwarded, `Origin: https://grafana.happy-mining.de` vs. `Host: grafana.lan:3000` never matched, so Grafana rejected the panel data requests. (Confirmed by the symptom itself: direct `http://grafana.lan:3000` access — no proxy involved — worked fine, while both the iframe **and** directly browsing `https://grafana.happy-mining.de` failed identically, ruling out anything iframe/embedding-specific.)
- **Fix:** added the missing `proxy_set_header Host $host;` to `grafana.conf`.

### 3. Grafana panels not rendering at all (chrome visible, panel area empty)
- **Root cause:** the tile's iframe was a fixed `220px` tall. Grafana's own nav/breadcrumb/search/login bar plus the variable- and time-range-picker header alone consume most of that, leaving ~0px for the panel grid. Grafana virtualizes panel rendering (only fetches data for panels with visible height), so panels never even attempted to load.
- **Fix:** `GrafanaTile.tsx` iframe height `220px → 560px`; both dashboard URLs in `tileRegistry.tsx` gained `&kiosk`, which drops Grafana's own top nav/search/login row (redundant here — access is anonymous, and Alice's own chrome already frames the tile) while keeping the variable/time-range controls, freeing more of that height for panels.

### 4. Cosmetic: excess tile padding on mobile
- Tiles used shadcn `Card`'s default `p-6` (24px) padding unchanged, plus the grid's own outer padding — compounding on a 375px phone into a large border with no information. `TileCard.tsx`: header/content padding `p-6` → `p-4`. `TileGrid.tsx`: outer padding/gap `p-4`/`gap-4` → `p-3`/`gap-3` on mobile (`sm:p-4`/`sm:gap-4` unchanged on wider screens).

### 5. Cosmetic: Weaviate schema tile order unstable
- **Root cause:** Weaviate's `/v1/schema` doesn't guarantee a stable order — it visibly reshuffled on every manual refresh.
- **Fix:** `admin_dashboard.py` — `classes` sorted alphabetically right after extraction from the schema response, before the count-aggregation query and before shaping.

## Deployment

**Production URL:** https://alice.happy-mining.de (Dashboard: `/dashboard`, admin-only)
**Deployed:** 2026-08-12
**Deployed by:** Andreas, with live-fix iteration alongside this session (see Live-Verification Follow-ups above)

**What shipped:**
- Backend: 3 new `alice-chat-stream` admin endpoints (Weaviate schema overview, running/failed n8n executions) — `app/admin_dashboard.py`, `app/main.py`. New env vars `N8N_API_URL`, `N8N_API_KEY`, `N8N_PUBLIC_URL` on `alice-chat-stream`.
- Frontend: new `/dashboard` route, shared chat/vision state between Dashboard and Chat, Nutzermenü Dashboard⇄Chat toggle, 6 tiles behind a central registry.
- Infra: new `docker/compose/infra/nginx/conf.d/grafana.conf` (same-origin HTTPS front for Grafana at `grafana.happy-mining.de`, reusing the existing wildcard cert). Grafana itself reconfigured (`allow_embedding`, anonymous Viewer access, `root_url`/`domain`) and a new Pi-hole DNS entry for `grafana.happy-mining.de` — both external to this repo, applied directly by the user on the Grafana host.

Verified live by the user: Weaviate/n8n tiles show real data, both Grafana dashboards render their panels, Dashboard↔Chat hand-off and Nutzermenü navigation work, alphabetical schema ordering confirmed stable across refreshes.
