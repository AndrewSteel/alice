# PROJ-54: Vision-Chat: Flip-Card Ergebnisansicht

## Status: Architected
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
_To be added by /qa_

## Deployment
_To be added by /deploy_
