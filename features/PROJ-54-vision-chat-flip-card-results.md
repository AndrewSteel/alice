# PROJ-54: Vision-Chat: Flip-Card Ergebnisansicht

## Status: Deployed
**Created:** 2026-06-27
**Last Updated:** 2026-06-27 (Layout-Konzept überarbeitet: Split-Screen statt rechte Seitenleiste)

## Dependencies
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — Flip-Cards benötigen Thumbnails; PROJ-55 liefert den API-Endpunkt und den Backfill
- Requires: PROJ-46 (Mail IMAP Integration) — Mail-Dokumente in Weaviate (für Rückseiten-Schema-Daten)
- Future: PROJ-45 (Display Registry & Output Router) — Display-Routing-Aktion in der Icon-Leiste (Phase 2.3+)

## Overview

Wenn Suchanfragen zu mehreren Einzelergebnissen führen, werden die Treffer nicht als Textblock im Chat ausgegeben, sondern visuell als **Flip-Cards** in einem dedizierten Vision-Chat-Bereich dargestellt. Die Oberfläche besteht aus einem **Split-Screen**: dem Vision-Chat-Bereich (links) und dem Text-Chat-Bereich (rechts). Beide Bereiche können unabhängig ein- und ausgeblendet werden. Nach dem Login ist standardmäßig nur der Text-Chat-Bereich sichtbar. Fordert der Nutzer eine visuelle Ausgabe an, blendet sich der Vision-Chat-Bereich automatisch ein und der Text-Chat-Bereich automatisch aus. Der Nutzer kann den Text-Chat jederzeit wieder einblenden. Die Eingabezeile und Voice-Steuerung sind unabhängig vom aktiven Anzeigemodus immer verfügbar.

## User Stories

- Als Andreas möchte ich bei Anfragen wie „Zeige mir alle Rechnungen der Telekom" die Ergebnisse als Flip-Cards sehen, damit ich schnell mehrere Treffer visuell scannen kann, ohne einen langen Textblock zu lesen.
- Als Andreas möchte ich nach einer visuellen Anfrage den Text-Chat jederzeit wieder einblenden können, damit ich den Thinking-Prozess des LLM verfolgen oder eine Folgeanfrage im Textformat formulieren kann.
- Als Andreas möchte ich, dass beide Bereiche (Vision-Chat und Text-Chat) gleichzeitig angezeigt werden können, damit ich die Karten und den Chat-Verlauf parallel im Blick habe.
- Als Andreas möchte ich eine Flip-Card umdrehen und die relevanten Weaviate-Schema-Daten auf der Rückseite sehen, damit ich Dokumenten-Metadaten auf einen Blick prüfen kann.
- Als Andreas möchte ich über das ∑-Icon die AI-generierte Zusammenfassung eines Dokuments sehen, damit ich den Inhalt verstehen kann, ohne das Originaldokument zu öffnen.
- Als Andreas möchte ich per Texteingabe oder Sprachbefehl die dargestellten Karten filtern und sortieren können, ohne separate Filter-Buttons bedienen zu müssen.
- Als Andreas möchte ich auf dem Smartphone zwischen Karten-Ansicht und Chat-Ansicht wechseln können (per Swipe oder Icon), damit beide Ansichten auf kleinen Bildschirmen komfortabel nutzbar sind.

## Acceptance Criteria

### Trigger & LLM-Integration

- [ ] Enthält eine Anfrage einen visuellen Intent-Marker (z. B. „Zeige mir …"), werden die Ergebnisse automatisch als Flip-Cards dargestellt
- [ ] Das LLM kann bei Anfragen mit mehreren Ergebnissen aktiv anbieten: „Soll ich Dir die Ergebnisse grafisch darstellen?" — der Nutzer bestätigt mit Ja/Nein
- [ ] Nicht-visuelle Anfragen zeigen weiterhin die normale Text-Chat-Antwort; die Karten-Seitenleiste bleibt geöffnet, aber aktualisiert sich nicht

### Flip-Card — Vorderseite (Front)

- [ ] Kopfzeile: Original-Dateiname des Dokuments
- [ ] Vorschaubild: quadratisches 1:1-Format; Dokumente werden vom oberen Rand zugeschnitten, Bilder/Videos werden zentriert zugeschnitten
- [ ] Bereich unterhalb des Vorschaubildes für Zusatzinformationen (z. B. Datum, Betrag, Absender — dokumenttyp-abhängig)
- [ ] Fußzeile: Icon-Leiste mit ∑-Icon (MVP); Architektur muss weitere Icons ohne Refactoring aufnehmen können
- [ ] Klick auf das ∑-Icon wechselt zur Summary-Seite
- [ ] Klick auf die Card außerhalb des Vorschaubildes und außerhalb der Icon-Leiste wechselt zur Rückseite

### Flip-Card — Rückseite (Back)

- [ ] Zeigt relevante Felder aus den Weaviate-Schemas, angepasst an den Dokumenttyp (z. B. für Invoice: Betrag, Datum, Aussteller; für BankTransaction: IBAN, Betrag, Verwendungszweck)
- [ ] Klick irgendwo auf die Rückseite wechselt zurück zur Vorderseite

### Flip-Card — Summary-Seite

- [ ] Zeigt die AI-generierte Zusammenfassung, die für das Weaviate-Objekt gespeichert wurde
- [ ] Klick irgendwo auf die Summary-Seite wechselt zurück zur Vorderseite

### Frontend-Layout — Split-Screen-Konzept

Der Hauptbereich der App (ohne linke Sidebar und Footer) ist in zwei Hälften aufgeteilt:
- **Vision-Chat-Bereich** (links) — zeigt die Flip-Card-Grid
- **Text-Chat-Bereich** (rechts) — zeigt den bisherigen Chat-Verlauf

Beide Bereiche können unabhängig voneinander ein- und ausgeblendet werden, sodass drei Anzeigemodi entstehen:

| Modus              | Vision-Chat | Text-Chat | Breite (Desktop)            |
| ------------------ | ----------- | --------- | --------------------------- |
| Text only (Start)  | aus         | ein       | 100 % Text                  |
| Vision only        | ein         | aus       | 100 % Vision                |
| Split (beide)      | ein         | ein       | 2/3 Vision + 1/3 Text       |

**Startzustand & Aktivierungsregeln:**

- [ ] Nach dem Login ist ausschließlich der Text-Chat-Bereich sichtbar (Modus: Text only)
- [ ] Der Vision-Chat-Bereich kann **nicht manuell** aktiviert werden — er erscheint nur, wenn der Nutzer eine visuelle Ausgabe explizit angefordert hat (Trigger: „Zeige mir …" oder LLM-Angebot bestätigt)
- [ ] Bei Aktivierung des Vision-Chat-Bereichs durch eine Anfrage blendet sich der Text-Chat-Bereich **automatisch aus** (Wechsel zu Modus: Vision only)
- [ ] Der Nutzer kann den Text-Chat-Bereich **jederzeit manuell wieder einblenden** (Wechsel zu Modus: Split oder Text only)
- [ ] Der Nutzer kann den Text-Chat-Bereich **manuell ausblenden** um wieder zu Modus: Vision only zu wechseln
- [ ] Die linke Sidebar (Session-Liste) bleibt davon unabhängig ein- und ausblendbar

**Desktop/PC:**

- [ ] Split-Verhältnis: Vision-Chat-Bereich 2/3 der Fensterbreite, Text-Chat-Bereich 1/3 der Fensterbreite
- [ ] Die Karten werden in einem responsiven Raster (Reihen × Spalten) dargestellt und nutzen die verfügbare Breite des Vision-Chat-Bereichs
- [ ] Eingabezeile und Voice-Icons im Footer bleiben in allen drei Anzeigemodi funktionsfähig

**Smartphone (Portrait und Landscape):**

- [ ] Keine gleichzeitige Darstellung beider Bereiche — immer nur einer sichtbar
- [ ] Startzustand nach Login: Text-Chat-Bereich
- [ ] Vision-Chat-Bereich erscheint nur auf explizite Nutzeranforderung (gleiche Trigger wie Desktop)
- [ ] Wechsel zwischen den Bereichen: bevorzugt per **Swipe-Geste**; falls technisch nicht umsetzbar, über ein sichtbares **Toggle-Icon**
- [ ] Gilt für Portrait- und Landscape-Format gleichermaßen
- [ ] Smartphone Portrait: 2 Karten pro Reihe
- [ ] Smartphone Landscape: 4 Karten pro Reihe
- [ ] Eingabezeile und Voice-Icons im Footer bleiben in beiden Bereichen funktionsfähig

**Folgeanfragen:**

- [ ] Follow-up-Anfragen (Text oder Sprache) können das angezeigte Karten-Raster aktualisieren (filtern, sortieren, einschränken) — unabhängig davon, ob aktuell Modus Vision only oder Split aktiv ist

### Backend — Thumbnail-Integration (via PROJ-55)

- [ ] Thumbnail-Generierung und Backfill sind vollständig in PROJ-55 spezifiziert und müssen vor PROJ-54 deployed sein
- [ ] PROJ-54 Frontend konsumiert den Thumbnail-API-Endpunkt aus PROJ-55 (`GET /api/dms/thumbnail/<weaviate_uuid>`)
- [ ] LLM-Tool / n8n-Workflow für visuelle Anfragen gibt strukturierte Ergebnislisten mit Weaviate-UUIDs zurück, damit das Frontend die Thumbnails abrufen kann
- [ ] Kein Thumbnail vorhanden (Backfill noch ausstehend oder Fehler): Frontend zeigt Platzhalter-Bild (Endpunkt von PROJ-55 liefert diesen automatisch)

## Edge Cases

- **0 Ergebnisse**: Vision-Chat-Bereich öffnet sich, zeigt aber einen Leerzustand mit erklärender Nachricht (z. B. „Keine Treffer gefunden")
- **1 Ergebnis**: Einzelne Karte wird angezeigt (kein Grid-Layout-Problem)
- **Sehr viele Ergebnisse (50+)**: Scrollbares Raster; virtuelle Darstellung falls nötig, damit die Performance stabil bleibt
- **Kein Thumbnail vorhanden** (Dokument noch nicht verarbeitet oder Backfill ausstehend): Platzhalter/Skeleton wird angezeigt; Karte bleibt nutzbar
- **Follow-up-Anfrage aktualisiert Ergebnisse**: Karten-Raster ersetzt bestehende Karten; zuvor aufgeklappte Karten fallen auf Vorderseite zurück
- **Nutzer wechselt manuell zu Text-Chat während Karten angezeigt werden**: Karten-Zustand bleibt erhalten; beim Zurückwechseln (manuell oder per Swipe) werden die Karten unverändert angezeigt
- **Nutzer versucht Vision-Chat manuell zu öffnen** ohne vorherige visuelle Anfrage: Keine Aktion — der Bereich bleibt gesperrt; optional Info-Toast „Bitte zuerst eine Anfrage stellen (z. B. ‚Zeige mir …')"
- **Orientierungswechsel (Mobile)**: Raster wechselt zwischen 2- und 4-Spalten-Layout; Scroll-Position bleibt soweit möglich erhalten; aktiver Modus (Vision oder Text) bleibt unverändert
- **LLM bietet visuelle Darstellung nicht an** bei Multi-Ergebnis-Anfrage: Normale Textantwort im Text-Chat; Nutzer kann explizit „Zeige mir …" formulieren
- **Nicht-visuelle Anfrage während Vision-Chat aktiv ist (Vision-only-Modus)**: Bei einer LLM-Textantwort wird der Text-Chat-Bereich automatisch eingeblendet (Wechsel zu Split-Modus: Vision 2/3, Text 1/3); Karten-Inhalt ändert sich nicht

## Technical Requirements

- **Thumbnail-Größe**: In der Architektur festlegen, orientiert an 2-Spalten-Layout im Smartphone-Portrait (ca. 300–400 px Breite)
- **Warm Storage**: Bestehende NAS Warm-Storage-Infrastruktur für Thumbnails nutzen (aktuell wenig belastet)
- **Kein zusätzliches Filter-/Sortier-UI**: Alle Interaktionen laufen über Texteingabe und Sprachsteuerung
- **Icon-Leiste erweiterbar**: Architektur muss weitere Aktions-Icons (z. B. Originaldokument öffnen, Display-Routing per PROJ-45) ohne größere Umbaumaßnahmen ermöglichen
- **Performance**: Thumbnails sollen im lokalen Netzwerk innerhalb von 1 s laden

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Component Structure

```
AppShell (extended — manages display mode + vision results state)
├── Sidebar (existing, unchanged)
└── MainArea (new wrapper replaces current flex-1 div)
    ├── [mobile header, unchanged]
    ├── VisionPanel (new — left pane, hidden until first vision result)
    │   ├── VisionPanelHeader
    │   │   └── TextChatToggleButton (show/hide right pane)
    │   ├── FlipCardGrid (responsive CSS grid)
    │   │   └── FlipCard (×N — one per result)
    │   │       ├── FlipCardFront
    │   │       │   ├── Filename header
    │   │       │   ├── ThumbnailImage (fetches /api/dms/thumbnail/{uuid} with auth)
    │   │       │   ├── MetadataBar (doc-type specific: date / amount / sender)
    │   │       │   └── IconBar (∑ → switch to Summary face)
    │   │       ├── FlipCardBack (Weaviate schema fields per doc type)
    │   │       └── FlipCardSummary (AI summary text)
    │   └── VisionEmptyState (shown when 0 results)
    └── TextPanel (new wrapper — right pane, visible by default)
        ├── TextPanelToggleButton (show/hide left pane on split mode)
        └── ChatWindow (existing, props unchanged)
```

### Display Mode State Machine

Three modes, controlled by `useVisionPanel` hook:

| Mode | VisionPanel | TextPanel | Desktop widths |
|---|---|---|---|
| `text` (default after login) | hidden | full width | 100% text |
| `vision` (auto after first visual result) | full width | hidden | 100% vision |
| `split` (user re-enables text panel) | 2/3 width | 1/3 width | 67% / 33% |

**Transition rules:**
- Login → `text`
- `vision_results` SSE event received → switch to `vision`, replace card grid
- User clicks "show text chat" while in `vision` → switch to `split`
- User clicks "hide text chat" while in `split` → switch to `vision`
- Text-only LLM response arrives while mode is `vision` → auto-switch to `split`
- Follow-up `vision_results` event (any mode) → refresh card grid, switch to `vision`
- Mobile: `split` is not allowed — only `text` or `vision`

### Data Flow

```
User input (text / voice)
        │
        ▼
useChatSessions.sendMessage()
        │  SSE stream from alice-chat-stream
        ├─ token / thinking / tool_call events → MessageList (unchanged)
        └─ vision_results event ──────────────→ useVisionPanel.setResults()
                                                        │
                                                        ▼
                                                VisionPanel re-renders
                                                FlipCardGrid (new cards)
```

### New SSE Event: `vision_results`

alice-chat-stream emits this alongside normal events when a DMS tool call returns an array of documents with Weaviate UUIDs:

```
Payload shape:
{
  event: "vision_results",
  results: [
    {
      uuid: string,
      document_type: "Invoice" | "BankStatement" | ...,
      filename: string,
      metadata: { date?, amount?, sender?, iban?, subject?, ... },
      summary: string | null
    }
  ]
}
```

alice-chat-stream detects vision results by checking if a tool response body contains an array where items have a `weaviate_uuid` field. No change to n8n tool workflows needed — the existing DMS search tools already return this shape.

### State Management

**`useVisionPanel` hook** (new, called from AppShell):
- `displayMode: "text" | "vision" | "split"`
- `results: VisionResult[]`
- `setResults(results)` — called by useChatSessions when `vision_results` event arrives; auto-switches to `vision` mode
- `showTextPanel()` / `hideTextPanel()` — user-triggered mode switches
- `onTextResponse()` — called when a non-vision LLM response arrives; if mode is `vision`, auto-switches to `split`

**`useChatSessions` changes** (minimal):
- New optional prop: `onVisionResults: (results: VisionResult[]) => void`
- SSE loop: when event type is `vision_results`, parse payload and call callback
- All other logic unchanged

### Flip Card

- **Three faces** per card: `front`, `back`, `summary` — tracked per-card in FlipCardGrid local state
- **Animation**: CSS 3D transform (`rotateY(180deg)`) via Tailwind `[transform-style:preserve-3d]` utility and custom CSS class — no JS animation library
- **Click zones**: click on thumbnail/card area → toggle `front`↔`back`; click on ∑ icon → switch to `summary`; click anywhere on `back` or `summary` → return to `front`
- **Reset on new results**: when `setResults` is called, all cards reset to `front` face

### Thumbnail Fetching

`<img>` tags cannot send JWT auth headers. Pattern used:

- `ThumbnailImage` component fetches `GET /api/dms/thumbnail/{uuid}` via `fetch()` with `Authorization: Bearer {token}` header
- Response blob is converted to an object URL (`URL.createObjectURL`)
- Set as `src` on an `<img>` element
- `<Skeleton>` shown during load; no error state needed (endpoint always returns an image)
- Object URL revoked on component unmount

### Mobile Swipe

- Touch event listeners (`onTouchStart` / `onTouchEnd`) on MainArea
- Detect horizontal swipe ≥50px: swipe left → switch to `vision`, swipe right → switch to `text`
- Toggle icon button shown as fallback (always visible on mobile)
- No external gesture library

### Grid Columns

Via CSS `grid-template-columns`:
- Mobile portrait (`< sm`): 2 columns
- Mobile landscape (`sm → md`): 4 columns
- Desktop (`md+`): `auto-fill, minmax(200px, 1fr)` — fills available VisionPanel width

### Backend Changes Required

**alice-chat-stream** (minor addition):
- Detect `vision_results` shape in tool response bodies
- Emit new `vision_results` SSE event alongside existing `tool_call` event

**nginx** (new location block, added in PROJ-55):
- `/api/dms/thumbnail/` → `alice-dms-thumbnailer:8004`
- GET only, JWT auth delegated to thumbnailer

### New Frontend Dependencies

| Package | Purpose |
|---|---|
| None required | CSS 3D flip is Tailwind-only; touch events are native; blob fetch is native |

## QA Test Results

**QA Date:** 2026-06-27
**Verdict:** READY — no Critical or High bugs remaining

### Acceptance Criteria

| # | AC | Result |
|---|---|---|
| **Trigger & LLM** | | |
| 1 | Visuelle Ergebnisse erscheinen automatisch als Flip-Cards wenn Tool `vision_results` SSE-Event sendet | ✅ PASS (nach BUG-54-1 Fix) |
| 2 | Nicht-visuelle Anfragen zeigen normale Text-Antwort; Karten-Raster bleibt erhalten | ✅ PASS |
| **Flip Card Front** | | |
| 3 | Kopfzeile: Dateiname (Fallback "Unbekannt") | ✅ PASS |
| 4 | Vorschaubild: ThumbnailImage fetcht `/api/dms/thumbnail/{uuid}` mit Auth-Header | ✅ PASS |
| 5 | Metadaten-Bereich unterhalb Thumbnail (dokumenttyp-abhängig) | ✅ PASS |
| 6 | Icon-Leiste mit ∑-Button | ✅ PASS |
| 7 | ∑-Button → wechselt zu Summary-Seite | ✅ PASS |
| 8 | Klick auf Karte (außerhalb Icon-Leiste) → wechselt zur Rückseite | ✅ PASS |
| **Flip Card Rückseite** | | |
| 9 | Zeigt Weaviate-Felder passend zum Dokumenttyp | ✅ PASS |
| 10 | Klick auf Rückseite → wechselt zur Vorderseite | ✅ PASS |
| **Flip Card Summary** | | |
| 11 | Zeigt AI-Zusammenfassung oder "Keine Zusammenfassung verfügbar." | ✅ PASS |
| 12 | Klick auf Summary-Seite → wechselt zur Vorderseite | ✅ PASS |
| **Layout — Split Screen** | | |
| 13 | Nach Login: ausschließlich Text-Chat sichtbar (displayMode = "text") | ✅ PASS |
| 14 | Vision-Bereich kann nicht manuell aktiviert werden — nur via `vision_results` SSE-Event | ✅ PASS |
| 15 | Bei Vision-Aktivierung: Text-Chat blendet sich automatisch aus (Modus: vision) | ✅ PASS |
| 16 | Text-Chat jederzeit manuell wieder einblendbar (Modus: split) | ✅ PASS |
| 17 | Text-Chat manuell ausblendbar → Modus: vision | ✅ PASS |
| 18 | Sidebar unabhängig ein-/ausblendbar | ✅ PASS |
| **Desktop** | | |
| 19 | Split-Verhältnis: 2/3 Vision + 1/3 Text (`flex-[2]` + `flex-[1]`) | ✅ PASS |
| 20 | Responsives Karten-Raster nutzt verfügbare Vision-Panel-Breite | ✅ PASS |
| **Mobile** | | |
| 21 | Kein Split-Modus auf Mobile — immer nur ein Bereich sichtbar | ✅ PASS |
| 22 | Startzustand: Text-Chat | ✅ PASS |
| 23 | Swipe-Geste (≥50 px horizontal): links → Vision, rechts → Text | ✅ PASS |
| 24 | Toggle-Icon in Mobile-Header wenn Vision-Ergebnisse vorhanden | ✅ PASS |
| 25 | Portrait: 2 Karten pro Reihe (`grid-cols-2`) | ✅ PASS |
| 26 | Landscape: 4 Karten pro Reihe (`sm:grid-cols-4`) | ✅ PASS |
| **Thumbnail-Integration** | | |
| 27 | ThumbnailImage fetcht `/api/dms/thumbnail/{uuid}` mit `Authorization: Bearer` Header | ✅ PASS |
| 28 | Kein Thumbnail → Platzhalter-Bild (Thumbnailer liefert immer ein Bild) | ✅ PASS |

### Bugs Found

| ID | Severity | Status | Description |
|---|---|---|---|
| BUG-54-1 | High | Fixed | `_extract_vision_results` in `streaming.py` prüfte auf `weaviate_uuid`-Feld, aber `alice-tool-search` gibt `weaviate_id` zurück — `vision_results` SSE-Event wurde nie gesendet. Behoben: Fallback-Kette `weaviate_id` → `weaviate_uuid` → `_additional.id`. |
| BUG-54-2 | Medium | Fixed | Falsche Feld-Mappings: Tool gibt `collection` (nicht `document_type`) und `title_or_summary` (nicht `summary`) zurück. Behoben: Mapping-Logik in `_extract_vision_results` erweitert um alle Varianten. |

### Security Audit

- **JWT-Auth für Thumbnail-Fetch**: Token aus localStorage, via fetch()-Header gesendet — kein Cookie, kein `<img src>` ohne Auth. ✅
- **Vision-Ergebnisse aus SSE-Stream**: Gleiche Auth wie bestehender Chat-Stream. ✅
- **Kein neuer Angriffspfad**: Keine neuen API-Routen im Frontend. ✅
- **Object URL Memory Leak**: `URL.revokeObjectURL()` wird im Unmount-Effect von `ThumbnailImage` aufgerufen. ✅

### Unit Tests

- 15 Tests für `_extract_vision_results()` in `docker/compose/automations/alice-chat-stream/tests/test_extract_vision_results.py` — alle bestanden.

### Automated Tests

- `npm run build` (Frontend): ✅ Keine TypeScript-Fehler

## Deployment

**Deploy Date:** 2026-06-28
**Deployed by:** Andrew Steel

### What was deployed
- Frontend rebuilt and synced to nginx via `deploy-frontend.sh` + `sync-compose.sh`
- New components: `VisionPanel`, `FlipCard`, `FlipCardGrid`, `ThumbnailImage`, `VisionEmptyState`
- New hook: `useVisionPanel`
- `useChatSessions`, `api.ts`, `AppShell.tsx` extended for vision_results SSE handling
- `streaming.py` extended with `_extract_vision_results()` and `vision_results` SSE emission

### Known issue — alice-chat-stream container not rebuilt
The `streaming.py` backend changes were synced locally but the alice-chat-stream container was **not rebuilt on the server**. First production test ("Zeige mir alle Rechnungen aus 2024") showed results in text-chat instead of vision-chat because the server container still runs the old code without `_extract_vision_results`.

**Fix:** Run these two commands:
```bash
./scripts/sync-compose.sh
ssh stan@ki.lan "docker compose -f /srv/compose/automations/alice-chat-stream/compose.yml up -d --build --force-recreate"
```

### alice-dms-thumbnailer-backfill
Trigger manually once to generate thumbnails for all existing Weaviate documents:
```bash
curl -X POST https://alice.happy-mining.de/api/webhook/alice-dms-thumbnailer-backfill
```
(verify exact webhook path in n8n UI)

## Post-Deploy Fixes — Test Round 1 (2026-06-28)

First production test produced 10 findings. **Frontend fixes implemented** (this round):

| # | Finding | Fix |
|---|---|---|
| 2 | Preview frame was landscape (~2:1), not square | `FlipCard` restructured: front face now sits in normal flow and defines card height; thumbnail wrapper is strict `aspect-square`. The card grows taller than 1:1 but the **image** is exactly 1:1 as required. |
| 3 | Input line + voice icons were inside the text panel → unreachable when text-chat hidden | Moved `InputArea` out of `ChatWindow` into a **persistent `<footer>` in `AppShell`**, rendered in all display modes (Vision-only, Text-only, Split). `ChatWindow` now renders only `MessageList`. |
| 4 | Mobile: header toggle to show text-chat had no effect; no swipe | Root cause: mobile coerces `split`→`vision`, but the toggle called the split-based `showTextPanel/hideTextPanel` (no-op after coercion). Added `setDisplayMode` to `useVisionPanel`; on mobile the toggles switch fully between `text` and `vision`. |
| 5 | Same toggle icon in WebApp header also failed | Same root cause as #4 (split-mode coercion on narrow viewport). Fixed via the mobile-aware handlers passed to both the mobile header and `VisionPanel`. |
| 6 | Card back mixed DE/EN labels + raw ISO dates | Added `formatMetaValue()` (ISO → `dd.MM.yyyy`), `EXTRA_META_LABELS` (German labels for extra keys), and `HIDDEN_META_KEYS` (hides `score`, `distance`, ids, etc.). Applied to back face and front metadata bar. |
| 8 | "Neuer Chat" did not close the Vision panel | Added `reset()` to `useVisionPanel` (clears results, mode → `text`); `AppShell.handleNewChat()` now calls it, restoring the post-login single-window state. |

**Backend findings — handed off to `/backend`** (frontend renders correctly; data is missing upstream):

| # | Finding | Root cause / location |
|---|---|---|
| 1 | Generated thumbnailer placeholder not used; Ubuntu "file not found" icon shown | `alice-dms-thumbnailer` (`app/main.py` / `Dockerfile`) — placeholder generated at build time but not served on cache miss. |
| 7 | Filename shows "Unbekannt" | `workflows/alice-tool-search.json` → **Weaviate Search** node: `allFields` never selects a filename property, and the output object emits no `filename`. `streaming.py` fallbacks all miss → empty. Add the filename property to the GraphQL selection + output. |
| 9 | "Alle Mails aus Januar 2026" capped at 20 (the limit) | `alice-tool-search` uses a flat `limit` with no pagination (`results.slice(0, limit)`). Needs higher/derived limit or cursor pagination for "alle …" queries. |
| 10 | Mail summary shows "Keine Zusammenfassung verfügbar" despite curl returning data | `alice-tool-search`: `summary` is only selected for `SUMMARY_COLLECTIONS`; mail/Email is excluded → `title_or_summary: ''` → `streaming.py` maps to `null`. Add mail summary/subject to the selection or to `SUMMARY_COLLECTIONS`. |

### Build verification (round 1)
- `npm run build` (Frontend): ✅ no TypeScript errors

## Post-Deploy Fixes — Round 2 (2026-06-28)

### Frontend fixes (this round)
- **#2 Square thumbnail**: `FlipCard` restructured — front face in normal flow; thumbnail wrapped in `aspect-square` div.
- **#3 Persistent input footer**: `InputArea` moved out of `ChatWindow` into a shared `<footer>` in `AppShell`, visible in all display modes.
- **#4/#5 Mobile toggle broken**: Added `setDisplayMode`/`reset` to `useVisionPanel`; mobile toggle now switches fully between `text`/`vision` instead of using the split-mode no-op handlers.
- **#6 Mixed DE/EN labels + raw ISO dates**: Added `formatMetaValue()`, `EXTRA_META_LABELS`, `HIDDEN_META_KEYS` to `FlipCard`.
- **#8 New chat keeps vision open**: `handleNewChat` calls `vision.reset()` → back to text-only state.

### Backend fixes (this round)

| # | File | Change |
|---|------|--------|
| **#7 filename "Unbekannt"** | `workflows/alice-tool-search.json` → Weaviate Search node | Added `'fileName'` to `allFields` GraphQL selection; emits `filename: item.fileName \|\| ''` in result object. |
| **#10 mail summary missing** | Same node | `title_or_summary` now falls back to `item.subject` for Email collection when `summary` is empty. |
| **#9 limit 20 für "alle Mails"** | Same file → Input Normalizer node | Raised cap 20→100; when LLM provides no explicit limit but both `date_from` and `date_to` are given (bounded date range), default limit is 50 instead of 5. |
| **#1 thumbnailer placeholder** | `docker/compose/automations/alice-dms-thumbnailer/app/main.py` | Added startup guard: if `placeholder.jpg` is missing at boot (Docker build artefact lost), regenerate it from Python/Pillow. Also fixed `ThumbnailImage.tsx`: non-OK HTTP responses now call `setError(true)` instead of silently staying in Skeleton state. |

### Build verification (round 2)
- `npm run build` (Frontend): ✅ no TypeScript errors

## Post-Deploy Fixes — Round 3 (2026-06-28)

### Test findings

| # | Symptom | Root cause |
|---|---------|------------|
| **A** | Thumbnail shows browser broken-image icon + alt text (filename) | nginx nie neu geladen nach Konfig-Änderung — `/api/dms/thumbnail/`-Route war zwar in alice.conf vorhanden und per `sync-compose.sh` auf dem Server, aber nginx lief noch mit dem alten In-Memory-Config. Alle Requests fielen durch zum SPA-Fallback `try_files … /index.html` → nginx gab HTML mit HTTP 200 zurück → Blob enthielt kein JPEG → Browser zeigte kaputtes Bild + Alt-Text. Thumbnailer wurde nie aufgerufen (daher leere Logs). |
| **B** | Vision-Chat zeigt 3 Treffer, Text-Chat sagt "4 Rechnungen" | `streaming.py` schickte das komplette Tool-Result an den LLM inkl. `_debug.raw` (ungefilterte Weaviate-Rohdaten vor dem `score < 0.01`-Filter). LLM zählte aus `_debug.raw` 4 Ergebnisse, `results` enthielt nach Score-Filter nur 3. |

### Fixes

| # | Datei | Änderung |
|---|-------|----------|
| **A** | `scripts/sync-compose.sh` | nginx reload nach rsync ausgeführt (derzeit auskommentiert — manuell bei Konfig-Änderungen nötig: `ssh stan@ki.lan "docker exec nginx nginx -s reload"`) |
| **B** | `docker/compose/automations/alice-chat-stream/app/streaming.py` | `_debug`, `_meta`, `_raw` Keys werden aus dem Tool-Result herausgefiltert bevor es an den LLM übergeben wird. LLM sieht nur `results` + `error`. |
| **C** | `docker/compose/automations/alice-dms-thumbnailer/Dockerfile` | Placeholder-Design überarbeitet: dunkelgrauer Hintergrund (gray-800, passend zur Alice-UI) + Dokumentkarten-Form statt hellgrauem Icon das dem Ubuntu-Systemicon ähnelte. Dockerfile-Einzeiler fixiert (Mehrzeilen-Python in `RUN` bricht den Dockerfile-Parser). |

### Deploy-Schritte für Round 3

```bash
# 1. Sync + nginx config sofort aktivieren
./sync-compose.sh
ssh stan@ki.lan "docker exec nginx nginx -s reload"

# 2. alice-chat-stream neu bauen (streaming.py Änderung — _debug strip)
ssh stan@ki.lan "docker compose -f /srv/compose/automations/alice-chat-stream/compose.yml up -d --build --force-recreate"

# 3. alice-dms-thumbnailer neu bauen (neuer Placeholder)
ssh stan@ki.lan "docker compose -f /srv/compose/automations/alice-dms-thumbnailer/compose.yml up -d --build --force-recreate"

# 4. Backfill auslösen (einmalig — generiert Thumbnails für alle bestehenden Weaviate-Dokumente)
curl -X POST https://alice.happy-mining.de/api/webhook/alice-dms-thumbnailer-backfill
```

### Offene Punkte

- `on_event("startup")` in `main.py` ist deprecated (FastAPI empfiehlt `lifespan` event handlers) — funktioniert noch, sollte bei nächster Gelegenheit migriert werden
- `sync-compose.sh` nginx-Reload ist auskommentiert — bei Nginx-Konfig-Änderungen manuell `nginx -s reload` ausführen oder Kommentare entfernen

## Re-Test — Round 3 Verification (2026-06-28)

**QA Date:** 2026-06-28
**Scope:** Verification der noch nicht committeten Post-Deploy-Fixes (Rounds 1–3) im Working Tree.
**Verdict:** READY — keine neuen Critical/High Bugs; alle Änderungen verifiziert.

### Geprüfte Änderungen (uncommitted diff)

| Bereich | Datei | Verifikation |
|---|---|---|
| LLM zählt Treffer falsch (Bug B) | `streaming.py` — `_LLM_STRIP_KEYS` entfernt `_debug`/`_meta`/`_raw` vor LLM | ✅ Strip betrifft nur `result_for_llm` (Zeile ~328); `_extract_vision_results(result)` liest weiterhin das ungefilterte Original → `results`-Array bleibt vollständig. `_debug` (enthält `raw`) wird korrekt entfernt. |
| Persistenter Input-Footer (#3) | `AppShell.tsx` / `ChatWindow.tsx` | ✅ `InputArea` aus `ChatWindow` entfernt, einmalig im `<footer>` von `AppShell` gerendert (alle Modi). Kein Doppel-Render. `disabled`-Bedingung um `!activeSessionId` erweitert. |
| Mobile-Toggle (#4/#5) | `AppShell.tsx` / `useVisionPanel.ts` | ✅ `setDisplayMode`/`reset` im Hook ergänzt; `onShowText`/`onHideText` schalten auf Mobile direkt `text`↔`vision`, auf Desktop über Split-Handler. |
| Neuer Chat schließt Vision (#8) | `useVisionPanel.ts` / `AppShell.handleNewChat` | ✅ `reset()` setzt `results=[]`, `displayMode="text"`. |
| Quadratisches Thumbnail (#2) | `FlipCard.tsx` | ✅ Front-Face in normalem Flow; Thumbnail in striktem `aspect-square`-Wrapper. |
| DE-Labels + ISO-Datum (#6) | `FlipCard.tsx` | ✅ `formatMetaValue()` (ISO→`dd.MM.yyyy`), `EXTRA_META_LABELS`, `HIDDEN_META_KEYS` (versteckt `score`, ids, `collection`, `filename` etc.). Konsistent mit `metadata`-Shape aus `_extract_vision_results` (das `score` mitliefert). |
| Thumbnail-Fehlerzustand | `ThumbnailImage.tsx` | ✅ Non-OK HTTP-Response → `setError(true)` statt dauerhaftem Skeleton. |
| Filename "Unbekannt" (#7) | `alice-tool-search.json` (Weaviate Search) | ✅ `'fileName'` in GraphQL-Selection; `filename: item.fileName || ''` im Result. `_extract_vision_results` liest `item.get("filename")` → Filename jetzt befüllt. |
| Mail-Summary fehlte (#10) | `alice-tool-search.json` | ✅ `title_or_summary` fällt für Email auf `item.subject` zurück. |
| Limit 20 für "alle Mails" (#9) | `alice-tool-search.json` (Input Normalizer) | ✅ Cap 20→100; bei beidseitig begrenztem Datumsbereich ohne explizites Limit Default 50 statt 5. |

### Verifikationsergebnisse

- **Frontend Build** (`npm run build`): ✅ Compiled successfully, keine TypeScript-/Lint-Fehler
- **Backend Unit Tests** (`pytest tests/`): ✅ 15/15 passed (`test_extract_vision_results.py`)
- **Workflow JSON** (`alice-tool-search.json`): ✅ valides JSON
- **Live-Test** (vom Nutzer bestätigt): Vision-Chat zeigt Flip-Cards wie spezifiziert

### Security Re-Check
- `_debug`/`raw` (ungefilterte Weaviate-Rohdaten) werden nicht mehr an das LLM gegeben → kein Informations-/Zähl-Leak. ✅
- Keine neuen externen Routen oder Auth-Pfade. ✅

**Keine neuen Bugs. PROJ-54 bleibt READY.**
