# PROJ-35: Chat Frontend Redesign — Nachrichten- und Eingabebereich

**Status:** Planned
**Created:** 2026-05-10
**Last Updated:** 2026-05-10

## Kontext & Motivation

Das bestehende Chat-Frontend (PROJ-31) wurde als funktionaler Streaming-Prototyp gebaut. Die aktuelle MessageBubble-Architektur stößt an Grenzen:

- Zwischenergebnisse (Tool-Calls, Thinking-Phasen) erscheinen als separate Bubbles, was zu visuellem Rauschen führt
- Das Segment-Modell (italic/normal innerhalb einer Bubble) ist zu komplex für den Nutzen
- Die Textbreite ist auf großen Screens nicht begrenzt
- Syntax Highlighting fehlt in Codeblöcken
- Die Komponenten-Granularität erschwert zukünftige Erweiterungen (Audio, Vision, Tool-UI)

Das Redesign ersetzt ausschließlich den Nachrichten- und Eingabebereich. Sidebar, Header, Auth und Nutzerverwaltung bleiben unverändert.

## Abgrenzung

**In Scope:**
- `MessageList` — scrollbarer Nachrichtenbereich
- `MessageBubble` / Nachrichtentypen-Rendering
- `InputArea` — Eingabebereich mit Auto-Grow-Textarea
- `useChatSessions` Hook (soweit der Nachrichten-State betroffen ist)
- Streaming-Rendering-Logik

**Out of Scope (bleibt unverändert):**
- Sidebar & Session-Verwaltung
- Header & Navigation
- Auth-Flows (LoginScreen, AuthProvider, ProtectedRoute)
- Nutzerverwaltung (Settings-Seite)
- Backend (alice-chat-stream, nginx, n8n)

## User Stories

- Als Nutzer möchte ich KI-Antworten dokumentenartig (kein Bubble-Design) lesen, damit ich auch lange strukturierte Ausgaben gut lesen kann.
- Als Nutzer möchte ich, dass meine eigenen Nachrichten kompakt und rechtsbündig erscheinen, damit der Chat-Fluss klar erkennbar bleibt.
- Als Nutzer möchte ich Codeblöcke mit Syntax Highlighting sehen, damit Code lesbar ist.
- Als Nutzer möchte ich, dass die Textbreite auch auf großen Monitoren maximal 760px beträgt, damit die Lesbarkeit erhalten bleibt.
- Als Nutzer möchte ich, dass bei laufendem Streaming die Seite nur dann automatisch scrollt, wenn ich mich am unteren Rand befinde, damit ich nicht beim Scrollen nach oben gestört werde.
- Als Nutzer möchte ich Zwischenergebnisse (Tool-Calls, Thinking) als fließenden Text im KI-Nachrichtenbereich sehen, nicht als separate Bubble.
- Als Nutzer möchte ich mit Shift+Enter Zeilenumbrüche in der Eingabe erzeugen, damit ich mehrzeilige Nachrichten schreiben kann.

## Acceptance Criteria

### Layout & Responsivität
- [ ] Gesamte Chat-Fläche (Nachrichten + Eingabe) ist innerhalb einer zentrierten Spalte mit `max-w-[760px]` gerendert
- [ ] Layout funktioniert auf 375px (Mobile), 768px (Tablet) und 1440px (Desktop)
- [ ] Nachrichtenbereich ist vertikal scrollbar, Eingabebereich bleibt fixiert am unteren Rand
- [ ] Kein horizontaler Scrollbalken auf keiner Viewport-Größe

### Nachrichtenbereich
- [ ] KI-Nachrichten werden dokumentenartig gerendert: kein Bubble-Hintergrund, volle Breite des Inhaltsbereichs, linksbündig
- [ ] Benutzernachrichten: kompaktes Bubble-Design, rechtsbündig, visuell abgesetzt (Hintergrundfarbe)
- [ ] Fehlermeldungen: eigene Darstellung (roter Rand / Icon), klar von normalen Nachrichten getrennt
- [ ] Streaming-Cursor (blinkender `|`) erscheint am Ende der aktiven KI-Antwort während des Streamings
- [ ] Typing-Indicator (3 Punkte) erscheint wenn gewartet wird und noch kein Token angekommen ist
- [ ] Tool-Status-Chip erscheint während aktiver Tool-Ausführung (ersetzt Typing-Indicator)
- [ ] Zwischenergebnisse vor Tool-Calls (LLM-Text) werden im selben KI-Nachrichtenblock als fließender Text gerendert — kein separater Bubble, kein Italic-Hack

### Markdown & Syntax Highlighting
- [ ] Überschriften (h1–h4), Listen (ul/ol), Blockquotes, horizontale Linien werden korrekt gerendert
- [ ] Tabellen werden gerendert (remark-gfm)
- [ ] Inline-Code: monospace, visuell abgesetzt
- [ ] Codeblöcke: Syntax Highlighting via `rehype-highlight` für mindestens TypeScript, JavaScript, Python, YAML, JSON, Bash
- [ ] Codeblöcke haben horizontalen Scroll bei langen Zeilen (kein Überlauf)
- [ ] Links öffnen in neuem Tab mit `rel="noopener noreferrer"`

### Eingabebereich
- [ ] Auto-Grow-Textarea wächst mit dem Inhalt (max. ~6 Zeilen, danach scrollbar innerhalb der Textarea)
- [ ] `Enter` sendet die Nachricht, `Shift+Enter` erzeugt Zeilenumbruch
- [ ] Sende-Button ist deaktiviert bei leerem Text oder während Loading/Streaming
- [ ] Während Streaming zeigt der Sende-Button ein Stopp-Icon; Klick bricht den Stream ab
- [ ] Eingabe wird nach dem Senden geleert

### Scroll-Verhalten
- [ ] Automatisches Scrollen erfolgt nur wenn der Nutzer sich ≤ 150px vom unteren Rand befindet
- [ ] Automatisches Scrollen erfolgt immer wenn eine neue Nachricht beginnt (Rollenwechsel)
- [ ] Während Streaming scrollt die Seite nicht bei jedem Token wenn der Nutzer nach oben gescrollt hat
- [ ] Nach Streaming-Ende: kein erzwungenes Scrollen

### State & Streaming
- [ ] `Message`-Typ enthält mindestens: `id`, `role` (`user` | `assistant` | `error`), `content`, `createdAt`, `streaming?`
- [ ] Streaming-Updates sind inkrementell (Token-Append auf letztem Assistant-Message)
- [ ] Abort (Stopp-Button): laufender Stream wird abgebrochen, Nachricht bleibt sichtbar mit `[Abgebrochen]`-Markierung
- [ ] Multi-Segment-Logik (`italic: true`) aus PROJ-31 wird entfernt — kein `segments`-Feld mehr im Message-Typ

### Erweiterbarkeit
- [ ] `Message`-Typ ist über optionale Felder erweiterbar (kein Breaking-Change für zukünftige Typen wie `toolCall`, `image`, `audio`)
- [ ] Nachrichtenrendering ist über eine zentrale `MessageRenderer`-Komponente gesteuert, die anhand `role` und optionalem `type` die passende Darstellung wählt
- [ ] Neue Nachrichtentypen können durch Registrierung eines neuen Renderers integriert werden, ohne bestehende Komponenten zu ändern

## Technologie-Entscheidungen

| Bereich | Technologie | Begründung |
|---|---|---|
| Framework | React + TypeScript | Bestand |
| Styling | TailwindCSS | Bestand |
| Markdown | react-markdown + remark-gfm | Bestand, bewährt |
| Syntax Highlighting | rehype-highlight | Neu, leichtgewichtig, SSR-kompatibel |
| State | React Context + useState (bestehender useChatSessions Hook) | Keine neue Abhängigkeit |
| Streaming | SSE (bestehendes streamChat aus api.ts) | Bestand |

**Warum rehype-highlight statt react-syntax-highlighter?**
rehype-highlight läuft als rehype-Plugin direkt in der Markdown-Pipeline und benötigt kein separates Bundle. Es nutzt highlight.js, das tree-shaking-fähig ist und nur die benötigten Sprachen mitlädt.

## Komponenten-Struktur (Ziel)

```
components/Chat/
├── ChatContainer.tsx          ← Layout-Wrapper (unverändert)
├── MessageList.tsx            ← Scrollbarer Bereich, Auto-Scroll-Logik
├── MessageRenderer.tsx        ← NEU: dispatcht auf den richtigen Renderer
├── renderers/
│   ├── AssistantMessage.tsx   ← Dokumentenartige KI-Nachricht + Markdown
│   ├── UserMessage.tsx        ← Kompakte rechtsbündige Bubble
│   └── ErrorMessage.tsx       ← Fehlermeldung mit Icon
├── TypingIndicator.tsx        ← Unverändert
├── ToolStatusChip.tsx         ← Unverändert
├── InputArea.tsx              ← Auto-Grow-Textarea + Send/Stop-Button
└── StreamingCursor.tsx        ← NEU oder inline: blinkender Cursor
```

`MessageBubble.tsx` wird durch `MessageRenderer.tsx` + `renderers/` ersetzt und kann danach gelöscht werden.

## Datenmodell

```typescript
// Minimales, erweiterbares Message-Interface
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  createdAt: number;           // Unix ms
  streaming?: boolean;
  // Zukunft (optional, kein Breaking Change):
  // type?: 'text' | 'tool_call' | 'image'
  // metadata?: Record<string, unknown>
}
```

Das `segments`-Feld aus dem gescheiterten PROJ-31 Ansatz entfällt vollständig.

## Abgrenzung Zwischenergebnisse (Tool-Call-Text)

LLM-Text, der vor einem Tool-Call produziert wird, ist regulärer `content` im Assistant-Message-Stream. Er wird identisch wie normaler Antworttext gerendert — kein Italic, keine separate Bubble, kein Styling-Unterschied. Die Unterscheidung zwischen "Zwischentext" und "Antworttext" entfällt auf Frontend-Seite vollständig.

## Dependencies

- Requires: PROJ-30 (alice-chat-stream Backend), PROJ-32 (nginx SSE-Proxy)
- Replaces: PROJ-31 Frontend-Komponenten (MessageBubble, segments-Logik)
- Modifies: `frontend/src/components/Chat/`, `frontend/src/hooks/useChatSessions.ts`
- New package: `rehype-highlight` + `highlight.js` (Sprach-Subsets)

## Deliverables

- [ ] `MessageRenderer.tsx` + `renderers/AssistantMessage.tsx`, `UserMessage.tsx`, `ErrorMessage.tsx`
- [ ] `MessageList.tsx` mit überarbeiteter Auto-Scroll-Logik
- [ ] `InputArea.tsx` mit Auto-Grow + Enter/Shift+Enter
- [ ] `useChatSessions.ts` — `segments`-Feld entfernt, `Message.id` hinzugefügt
- [ ] `MessageBubble.tsx` gelöscht (nach Migration)
- [ ] `rehype-highlight` installiert und konfiguriert
- [ ] Kein TypeScript-Fehler, Build erfolgreich
- [ ] Frontend deployed und auf ki.lan getestet
