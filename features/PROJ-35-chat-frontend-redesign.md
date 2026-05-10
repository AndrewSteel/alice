# PROJ-35: Chat Frontend Redesign — Nachrichten- und Eingabebereich

**Status:** Planned
**Created:** 2026-05-10
**Last Updated:** 2026-05-10

## Kontext & Motivation

Das bestehende Chat-Frontend (PROJ-31) wurde als funktionaler Streaming-Prototyp gebaut. Die aktuelle Architektur stößt an mehrere Grenzen:

- Zwischenergebnisse (Tool-Calls, Thinking-Phasen) erscheinen als separate Bubbles oder ToolStatusChip — beides visuell störend
- Das Segment-Modell (`italic: true` innerhalb einer Bubble) ist zu komplex und wurde verworfen
- Der ToolStatusChip ist eine Sackgasse: er kennt nur fünf fest verdrahtete Tool-Namen, ist nicht erweiterbar und zeigt keinen Kontext (welche Collection, welche Suchanfrage)
- Die Textbreite ist auf großen Screens nicht begrenzt
- Syntax Highlighting fehlt in Codeblöcken
- Typografie ist nicht differenziert — alle Rollen sehen gleich aus

Das Redesign ersetzt ausschließlich den Nachrichten- und Eingabebereich. Sidebar, Header, Auth und Nutzerverwaltung bleiben unverändert.

## Abgrenzung

**In Scope:**
- `MessageList` — scrollbarer Nachrichtenbereich
- `MessageRenderer` + rollenspezifische Renderer — ersetzen `MessageBubble`
- `InputArea` — Eingabebereich mit Auto-Grow-Textarea
- `useChatSessions` Hook (Nachrichten-State und Message-Typ)
- Streaming-Rendering-Logik
- Typografie des Nachrichtenbereichs

**Entfernt (Scope dieser Spec):**
- `MessageBubble.tsx` — wird durch `MessageRenderer` + `renderers/` ersetzt
- `ToolStatusChip.tsx` — wird gelöscht; Tool-Calls werden als eigene Nachrichtenrolle im Textstrom gerendert
- `segments`-Feld im Message-Typ — entfällt vollständig

**Out of Scope (bleibt unverändert):**
- Sidebar & Session-Verwaltung
- Header & Navigation
- Auth-Flows (LoginScreen, AuthProvider, ProtectedRoute)
- Nutzerverwaltung (Settings-Seite)
- Backend (alice-chat-stream, nginx, n8n)
- `TypingIndicator.tsx` — bleibt (zeigt 3 Punkte, solange noch kein erstes Token angekommen ist)

## User Stories

- Als Nutzer möchte ich KI-Antworten dokumentenartig lesen (kein Bubble-Design), damit ich auch lange strukturierte Ausgaben gut lesen kann.
- Als Nutzer möchte ich, dass meine eigenen Nachrichten kompakt und rechtsbündig erscheinen, damit der Chat-Fluss klar erkennbar bleibt.
- Als Nutzer möchte ich Tool-Calls und Thinking-Phasen als dezenten Fließtext im Nachrichtenbereich sehen — kleiner und heller als die eigentliche Antwort — damit ich den Systemstatus verfolgen kann, ohne abgelenkt zu werden.
- Als Nutzer möchte ich Codeblöcke mit Syntax Highlighting sehen, damit Code lesbar ist.
- Als Nutzer möchte ich, dass die Textbreite auch auf großen Monitoren maximal 760px beträgt, damit die Lesbarkeit erhalten bleibt.
- Als Nutzer möchte ich, dass bei laufendem Streaming die Seite nur dann automatisch scrollt, wenn ich mich am unteren Rand befinde, damit ich nicht beim Scrollen nach oben gestört werde.
- Als Nutzer möchte ich mit Shift+Enter Zeilenumbrüche in der Eingabe erzeugen, damit ich mehrzeilige Nachrichten schreiben kann.

## Acceptance Criteria

### Layout & Responsivität
- [ ] Gesamte Chat-Fläche (Nachrichten + Eingabe) ist innerhalb einer zentrierten Spalte mit `max-w-[760px]` gerendert
- [ ] Layout funktioniert auf 375px (Mobile), 768px (Tablet) und 1440px (Desktop)
- [ ] Nachrichtenbereich ist vertikal scrollbar, Eingabebereich bleibt fixiert am unteren Rand
- [ ] Kein horizontaler Scrollbalken auf keiner Viewport-Größe

### Nachrichtenbereich
- [ ] KI-Antworten (`assistant`): dokumentenartig, kein Bubble-Hintergrund, volle Inhaltsbreite, linksbündig
- [ ] Benutzernachrichten (`user`): kompaktes Bubble-Design, rechtsbündig, visuell abgesetzt (Hintergrundfarbe)
- [ ] Tool-Calls (`tool_call`): im Textstrom gerendert, dezent und kompakt, kein separates Widget; zeigt Tool-Name und optional Backend-gelieferten Statustext
- [ ] Thinking-Text (`thinking`): im Textstrom gerendert, dezent kleiner und heller; erscheint vor der eigentlichen Antwort
- [ ] Fehlermeldungen (`error`): roter Rand mit Icon, klar von normalen Nachrichten getrennt
- [ ] Systemmeldungen (`status`): neutraler Hinweistext (z.B. "Verbindung unterbrochen"), kein Bubble
- [ ] Streaming-Cursor (blinkender `|`) erscheint am Ende des aktiven Assistant- oder Thinking-Blocks während des Streamings
- [ ] Typing-Indicator (3 Punkte) erscheint, solange noch kein erstes Token und kein Tool-Call-Event angekommen ist
- [ ] `ToolStatusChip` wird nicht mehr verwendet

### Typografie

| Rolle | Schriftgröße | Schriftart | Farbe |
|---|---|---|---|
| `user` | 16px | Sans-Serif | `text-gray-100` |
| `assistant` | 16px | Sans-Serif | `text-gray-200` |
| `tool_call` | 14px | Sans-Serif | `text-gray-400` |
| `thinking` | 14px | Sans-Serif | `text-gray-400` |
| `error` | 14px | Sans-Serif | `text-red-300` |
| `status` | 13px | Sans-Serif | `text-gray-500` |

- [ ] Markdown-Überschriften in `assistant`-Nachrichten: proportional größer (h1 ≈ 22px, h2 ≈ 19px, h3 ≈ 17px), Schriftgewicht `semibold`, Farbe `text-gray-100`
- [ ] Fettschrift (`**text**`): `font-semibold`, Farbe `text-gray-100`
- [ ] Kursivschrift (`*text*`): `italic`, Farbe erbt von der Rolle
- [ ] Inline-Code: monospace, 13px, `bg-gray-800`, `text-pink-300`
- [ ] Codeblöcke: monospace, 13px, dunkler Hintergrund, Syntax Highlighting
- [ ] Tool-Call- und Thinking-Blöcke erben die 14px/`text-gray-400`-Typografie auch für enthaltenes Markdown (kein volles Prose-Styling)

### Markdown & Syntax Highlighting
- [ ] Überschriften (h1–h4), Listen (ul/ol), Blockquotes, horizontale Linien werden in `assistant`-Nachrichten korrekt gerendert
- [ ] Tabellen werden gerendert (remark-gfm)
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
- [ ] `Message`-Typ enthält die in „Datenmodell" definierten Felder
- [ ] Streaming-Updates sind inkrementell (Token-Append auf der zuletzt aktiven Nachricht)
- [ ] Tool-Call-Nachrichten werden aus SSE-Events `tool_start` / `tool_end` erzeugt und als eigenständige `Message`-Objekte in den Nachrichtenstrom eingefügt
- [ ] Abort (Stopp-Button): laufender Stream wird abgebrochen, letzte Nachricht bleibt sichtbar mit `[Abgebrochen]`-Markierung
- [ ] `segments`-Feld aus PROJ-31 ist entfernt

### Erweiterbarkeit
- [ ] `MessageRole` und `Message`-Typ sind in einer zentralen Typdatei definiert und von allen Komponenten importiert
- [ ] `MessageRenderer` dispatcht anhand `role` auf den zuständigen Renderer — neue Rollen erfordern nur einen neuen Renderer-Eintrag, keine Änderungen an bestehenden Komponenten
- [ ] `toolName`, `toolStatus` und `metadata` sind optionale Felder — das Hinzufügen weiterer optionaler Felder ist kein Breaking Change

## Datenmodell

```typescript
// Alle möglichen Nachrichtenrollen
type MessageRole =
  | 'user'       // Benutzereingabe
  | 'assistant'  // KI-Antworttext (Markdown, volle Typografie)
  | 'tool_call'  // Tool-Aufruf: Name + Statustext, 14px/grau
  | 'thinking'   // LLM-Zwischentext / Reasoning, 14px/grau
  | 'error'      // Fehlermeldung, roter Stil
  | 'status';    // Systeminformation (Verbindungsstatus o.ä.)

interface Message {
  id: string;
  role: MessageRole;
  content: string;           // Anzeigetext
  createdAt: number;         // Unix ms
  streaming?: boolean;       // true solange Tokens eintreffen

  // Nur bei role === 'tool_call':
  toolName?: string;         // interner Name, z.B. "search_documents"
  toolStatus?: 'running' | 'done' | 'error';

  // Erweiterungspunkte (heute leer, kein Breaking Change):
  // attachments?: Attachment[]
  // metadata?: Record<string, unknown>
}
```

**Mapping SSE-Events → MessageRole:**

| SSE-Event | Aktion |
|---|---|
| `token` | Append auf letzte `assistant`- oder `thinking`-Nachricht |
| `tool_start` | Neue `tool_call`-Nachricht mit `toolStatus: 'running'` einfügen |
| `tool_end` | `toolStatus` der passenden `tool_call`-Nachricht auf `'done'` oder `'error'` setzen |
| `error` | Neue `error`-Nachricht einfügen |
| `done` | `streaming: false` auf letzter aktiver Nachricht setzen |

Das `thinking`-Token-Mapping wird ergänzt, sobald das Backend Thinking-Events schickt (eigene Backend-Anforderung). Bis dahin ist die Rolle reserviert und wird nicht aktiv erzeugt.

## Komponenten-Struktur (Ziel)

```
components/Chat/
├── ChatContainer.tsx              ← Layout-Wrapper (unverändert)
├── MessageList.tsx                ← Scrollbarer Bereich, Auto-Scroll-Logik
├── MessageRenderer.tsx            ← NEU: dispatcht anhand role auf Renderer
├── renderers/
│   ├── AssistantMessage.tsx       ← 16px, Prose-Markdown, Syntax Highlighting
│   ├── UserMessage.tsx            ← 16px, rechtsbündige Bubble
│   ├── ToolCallMessage.tsx        ← 14px/grau, Tool-Name + Statustext
│   ├── ThinkingMessage.tsx        ← 14px/grau, Reasoning-Text (vorbereitet)
│   ├── ErrorMessage.tsx           ← roter Stil mit Icon
│   └── StatusMessage.tsx          ← 13px/grau, Systemhinweis
├── TypingIndicator.tsx            ← Unverändert (3 Punkte)
├── InputArea.tsx                  ← Auto-Grow-Textarea + Send/Stop-Button
└── types.ts                       ← NEU: MessageRole, Message, exportierte Typen

GELÖSCHT:
├── MessageBubble.tsx              ← ersetzt durch MessageRenderer + renderers/
└── ToolStatusChip.tsx             ← ersetzt durch ToolCallMessage-Renderer
```

## Abgrenzung Tool-Call-Rendering

Tool-Calls sind eigenständige `Message`-Objekte im Nachrichtenstrom — sie erscheinen zwischen dem Text, der vor dem Tool-Call erzeugt wurde, und dem Text danach. Beispiel für den Nachrichtenstrom bei einer Dokumentensuche:

```
[assistant] "Ich suche das für dich heraus."
[tool_call] toolName="search_documents", content="Suche in Dokumenten…", status=running
[tool_call] toolName="search_documents", content="Suche abgeschlossen", status=done
[assistant] "Hier sind die Ergebnisse: …"
```

Das `content`-Feld einer `tool_call`-Nachricht wird vom Backend geliefert (SSE `tool_start.status`). Ist es nicht vorhanden, zeigt der Renderer den `toolName` als Fallback. Das Frontend muss den Tool-Namen **nicht** übersetzen — das ist Aufgabe des Backends (eigene Backend-Anforderung).

## Technologie-Entscheidungen

| Bereich | Technologie | Begründung |
|---|---|---|
| Framework | React + TypeScript | Bestand |
| Styling | TailwindCSS | Bestand |
| Markdown | react-markdown + remark-gfm | Bestand, bewährt |
| Syntax Highlighting | rehype-highlight | Leichtgewichtig, läuft in der Markdown-Pipeline, tree-shaking-fähig |
| State | React Context + useState (useChatSessions Hook) | Keine neue Abhängigkeit |
| Streaming | SSE (bestehendes streamChat aus api.ts) | Bestand |

**Warum rehype-highlight statt react-syntax-highlighter?**
rehype-highlight läuft als rehype-Plugin direkt in der Markdown-Pipeline ohne eigenes Bundle. Es nutzt highlight.js mit tree-shaking — nur die benötigten Sprachen werden geladen.

## Dependencies

- Requires: PROJ-30 (alice-chat-stream Backend), PROJ-32 (nginx SSE-Proxy)
- Vorbereitung für: Backend-Anforderung Tool-Call-Kontext (noch zu schreiben — Backend soll `tool_start.status` mit beschreibendem Text liefern)
- Replaces: PROJ-31 Frontend-Komponenten (MessageBubble, ToolStatusChip, segments-Logik)
- Modifies: `frontend/src/components/Chat/`, `frontend/src/hooks/useChatSessions.ts`
- New package: `rehype-highlight` + `highlight.js` (Sprach-Subsets)

## Deliverables

- [ ] `frontend/src/components/Chat/types.ts` — `MessageRole`, `Message`-Interface
- [ ] `MessageRenderer.tsx` — Role-Dispatch
- [ ] `renderers/AssistantMessage.tsx` — Prose + Markdown + Syntax Highlighting
- [ ] `renderers/UserMessage.tsx` — 16px, rechtsbündige Bubble
- [ ] `renderers/ToolCallMessage.tsx` — 14px/grau, Tool-Name + Status
- [ ] `renderers/ThinkingMessage.tsx` — 14px/grau (vorbereitet, noch kein Backend-Event)
- [ ] `renderers/ErrorMessage.tsx` — roter Stil
- [ ] `renderers/StatusMessage.tsx` — neutraler Hinweistext
- [ ] `MessageList.tsx` — überarbeitete Auto-Scroll-Logik
- [ ] `InputArea.tsx` — Auto-Grow + Enter/Shift+Enter
- [ ] `useChatSessions.ts` — erweiterter Message-Typ, tool_call-Handling aus SSE-Events, segments entfernt
- [ ] `MessageBubble.tsx` — gelöscht
- [ ] `ToolStatusChip.tsx` — gelöscht
- [ ] `rehype-highlight` installiert und konfiguriert
- [ ] Kein TypeScript-Fehler, Build erfolgreich
- [ ] Frontend deployed und auf ki.lan getestet
