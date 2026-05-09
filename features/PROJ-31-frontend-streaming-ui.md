# PROJ-31: Frontend Streaming-UI

**Status:** 🟡 In Review
**Created:** 2026-05-07
**Last Updated:** 2026-05-08

## Kontext & Motivation

Das aktuelle React-Frontend sendet Nachrichten per `fetch()` und wartet auf die vollständige JSON-Antwort. Mit dem neuen `alice-chat-stream`-Service (PROJ-30) werden Antworten als Server-Sent Events (SSE) geliefert. Das Frontend muss umgebaut werden, um:

- Tokens sofort anzuzeigen (kein Warten auf vollständige Antwort)
- Tool-Status-Meldungen anzuzeigen ("Suche in Dokumenten…")
- Einen „Stopp"-Button anzubieten
- Verbindungsabbrüche und Fehler sauber zu behandeln

## Dependencies

- Requires: PROJ-30 (alice-chat-stream Backend mit SSE-Endpunkt)
- Modifies: `frontend/src/hooks/useChat.js`
- Modifies: `frontend/src/components/Chat/ChatContainer.*`
- Modifies: `frontend/src/components/Chat/MessageBubble.*`
- Modifies: `frontend/src/components/Chat/InputArea.*`
- Modifies: `frontend/src/services/api.js`

## User Stories

- Als Nutzer möchte ich sehen, wie die Antwort Wort für Wort aufgebaut wird, damit die Wartezeit sich kürzer anfühlt.
- Als Nutzer möchte ich einen Ladeindikator sehen, der zwischen „Denkt nach…" und „Sucht in Dokumenten…" unterscheidet, damit ich weiß, was Alice gerade macht.
- Als Nutzer möchte ich während einer laufenden Antwort auf „Stopp" klicken können, damit ich lange Antworten abbrechen kann.
- Als Nutzer möchte ich, dass das Eingabefeld während des Streamings deaktiviert ist, damit keine zwei Anfragen gleichzeitig laufen.
- Als Nutzer möchte ich bei einem Verbindungsfehler eine verständliche Meldung sehen und die Möglichkeit haben, erneut zu senden.

## Acceptance Criteria

### Streaming-Rendering
- [ ] Tokens werden sofort eingefügt, sobald sie als SSE-Event ankommen (kein Puffern)
- [ ] Die Nachrichtenblase wächst Zeichen für Zeichen, ohne zu flackern (keine kompletten Re-Renders)
- [ ] Markdown-Rendering (Fett, Kursiv, Code-Blöcke, Listen) funktioniert auch bei partiellem Text korrekt
- [ ] Nach `data: [DONE]` ist die Nachricht vollständig und unveränderlich

### Tool-Status-Anzeige
- [ ] Bei `type:"tool_start"` erscheint unterhalb der wachsenden Nachricht ein Status-Chip (z.B. „🔍 Suche in Dokumenten…")
- [ ] Bei `type:"tool_end"` verschwindet der Status-Chip
- [ ] Mehrere gleichzeitige Tools werden als separete Chips angezeigt
- [ ] HA-Tool-Status zeigt „💡 Schalte Licht ein…" (Tool-spezifische Labels)

### Stopp-Button
- [ ] Während des Streamings erscheint ein „Stopp"-Button im InputArea (ersetzt den Send-Button)
- [ ] Klick auf „Stopp" schließt die SSE-Verbindung sofort (`EventSource.close()`)
- [ ] Die bis zum Abbruch empfangene Antwort bleibt in der Nachrichtenblase sichtbar
- [ ] Nach Stopp wird die Nachricht mit `[Abgebrochen]`-Tag versehen
- [ ] Nach Stopp ist das Eingabefeld wieder aktiv

### Eingabefeld-Verhalten
- [ ] Während Streaming: Eingabefeld disabled, Send-Button versteckt, Stopp-Button sichtbar
- [ ] Rückkehr in normalen Zustand sobald Stream endet oder abgebrochen wird
- [ ] Enter-Taste während Streaming löst keine neue Anfrage aus

### Fehlerbehandlung
- [ ] SSE-Verbindungsfehler (Netzwerk) → Fehlermeldung in Chat: „Verbindung unterbrochen. Bitte erneut versuchen."
- [ ] `type:"error"` Event → Fehlermeldung als Assistenten-Nachricht in der Bubble
- [ ] HTTP 401 (abgelaufener JWT) → Redirect zur Login-Seite (analog zu bestehendem Auth-Flow)
- [ ] HTTP 429 (Rate-Limit) → Fehlermeldung: „Zu viele Anfragen – bitte kurz warten."

### API-Service
- [ ] `services/api.js` erhält neue Funktion `streamChat(sessionId, content, onToken, onToolStart, onToolEnd, onDone, onError)`
- [ ] Funktion gibt Objekt `{ abort }` zurück, mit dem der Stream abbrechbar ist
- [ ] Basis-URL konfigurierbar (Environment Variable `NEXT_PUBLIC_STREAM_API_URL`)
- [ ] JWT-Token wird aus `localStorage` gelesen und als `Authorization`-Header übergeben

### Rückwärtskompatibilität
- [ ] Bestehende Session-Persistenz (localStorage) bleibt unverändert
- [ ] Bestehende Sidebar, Session-Verwaltung, Authentifizierung bleiben unverändert
- [ ] Falls `NEXT_PUBLIC_STREAM_API_URL` nicht gesetzt ist, fällt der Chat auf den alten `fetch`-Endpunkt zurück

## Edge Cases

- Stream bricht mitten im Wort ab → Partielles Wort bleibt sichtbar, `[Abgebrochen]`-Tag
- Nutzer scrollt während Stream nach oben → Auto-Scroll deaktiviert sich, ohne den Stream zu beeinflussen
- Sehr lange Antwort (>5000 Zeichen) → Performance: nur neue Token werden gerendert, kein Re-Mount der gesamten Liste
- Tool-Status erscheint, Nutzer drückt Stopp → Status-Chip verschwindet sofort
- Mehrere Tabs offen, beide senden gleichzeitig → jeder Tab hat unabhängige SSE-Verbindung

## Technical Design

### Änderungen an `useChat.js`

```javascript
// Neue Funktion: streamMessage() statt sendMessage()
const streamMessage = async (content) => {
  setIsStreaming(true);
  appendUserMessage(content);
  const assistantId = appendEmptyAssistantMessage();

  const { abort } = streamChat(sessionId, content, {
    onToken: (token) => updateMessage(assistantId, token),
    onToolStart: (tool, status) => setToolStatus({ tool, status }),
    onToolEnd: (tool) => clearToolStatus(tool),
    onDone: () => { setIsStreaming(false); setToolStatus({}); },
    onError: (msg) => { updateMessageError(assistantId, msg); setIsStreaming(false); }
  });

  abortRef.current = abort;
};

const stopStreaming = () => {
  abortRef.current?.();
  setIsStreaming(false);
};
```

### Änderungen an `MessageBubble`

- Assistenten-Nachrichten im Streaming-Zustand erhalten `data-streaming="true"` Attribut
- Blinkender Cursor am Ende des Textes via CSS (kein JS-Interval)
- Markdown-Renderer erhält `partialRendering=true` Prop für toleranteres Parsing

### Änderungen an `InputArea`

```jsx
{isStreaming
  ? <Button onClick={stopStreaming} variant="destructive">Stopp</Button>
  : <Button type="submit" disabled={!content.trim()}>Senden</Button>
}
```

### Tool-Status-Komponente (neu)

```jsx
// frontend/src/components/Chat/ToolStatusChip.tsx
// Zeigt aktive Tools als animierte Chips unterhalb der Nachricht
const TOOL_LABELS = {
  search_documents: '🔍 Suche in Dokumenten…',
  get_document_details: '📄 Lade Dokument…',
  home_assistant: '💡 Steuere Gerät…',
  remember: '🧠 Merke mir…',
  recall: '🧠 Erinnere mich…',
};
```

### Deliverables

- [ ] `frontend/src/services/api.js` — neue `streamChat()`-Funktion
- [ ] `frontend/src/hooks/useChat.js` — Umbau auf Streaming
- [ ] `frontend/src/components/Chat/ToolStatusChip.tsx` — neue Komponente
- [ ] `frontend/src/components/Chat/InputArea.*` — Stopp-Button
- [ ] `frontend/src/components/Chat/MessageBubble.*` — Streaming-Cursor
- [ ] `.env.example` — `NEXT_PUBLIC_STREAM_API_URL=http://localhost:8003`

---

## Tech Design (Solution Architect)

### Komponenten-Übersicht

```
ChatWindow
├── MessageList
│   └── MessageBubble (jede Nachricht)
│       ├── Markdown-Inhalt (ERWEITERT: react-markdown)
│       ├── Blinkender Cursor [NEU: CSS-only, sichtbar wenn streaming]
│       └── ToolStatusChip-Reihe [NEU: aktive Tools unterhalb der Bubble]
└── ChatInputArea (ERWEITERT)
    ├── Textarea (disabled während Streaming)
    ├── Send-Button (ausgeblendet während Streaming)
    └── Stop-Button [NEU: sichtbar während Streaming]
```

### Datenhaltung (State)

Die bestehende `useChatSessions.ts` wird um drei neue Zustandsfelder erweitert:

```
Neuer Zustand in useChatSessions:
- isStreaming: boolean          → ob gerade ein Stream läuft (ersetzt isLoading)
- toolStatuses: Map             → welche Tools gerade aktiv sind (name → Label)
- abortRef                      → Handle zum Abbrechen der SSE-Verbindung
```

Nachrichten bleiben als Array in `messagesBySession` — der laufende Token-Stream aktualisiert den Inhalt der letzten Assistenten-Nachricht per ID, ohne das Array neu zu rendern.

### API-Layer (`services/api.ts`)

Neue Funktion `streamChat()` neben der bestehenden `sendMessage()`:

```
streamChat(sessionId, content, callbacks) → { abort }

Callbacks:
  onToken(text)          → Token sofort in Nachrichtenblase einfügen
  onToolStart(tool)      → Tool-Chip anzeigen
  onToolEnd(tool)        → Tool-Chip entfernen
  onDone()               → Stream beendet, Eingabe freischalten
  onError(message)       → Fehler als Assistenten-Nachricht anzeigen
```

**Warum `fetch()` statt `EventSource`:** Die Browser-native `EventSource`-API unterstützt keine benutzerdefinierten HTTP-Header — JWT im `Authorization`-Header wäre damit nicht möglich. Wir nutzen stattdessen `fetch()` mit manuellem SSE-Zeilenparsen aus dem `ReadableStream`.

### Fallback-Verhalten

```
NEXT_PUBLIC_STREAM_API_URL gesetzt?
  Ja  → streamChat() → POST /stream/chat (SSE)
  Nein → sendMessage() → bisheriger Endpunkt (unverändertes Verhalten)
```

Alle bestehenden Funktionen (Sessions, Authentifizierung, Sidebar) bleiben unberührt.

### Markdown-Rendering

`MessageBubble` rendert derzeit nur Plaintext. Für formatierte Assistenten-Antworten (Fett, Code, Listen) wird `react-markdown` + `remark-gfm` eingeführt. Das Partial-Rendering (laufender Stream) wird von react-markdown nativ toleriert — unvollständige Tokens werden nicht als Fehler behandelt.

### Tech-Entscheidungen

| Entscheidung     | Gewählt                                | Begründung                                             |
| ---------------- | -------------------------------------- | ------------------------------------------------------ |
| SSE-Transport    | `fetch()` + ReadableStream             | JWT-Header nicht via EventSource möglich               |
| Token-Updates    | ID-basiertes In-Place-Update           | Kein Re-Render der gesamten Nachrichtenliste pro Token |
| Streaming-Cursor | CSS `::after` + Keyframe               | Kein JS-Interval nötig, kein Flackern                  |
| Markdown         | react-markdown + remark-gfm            | Partial-Rendering-tolerant, etablierte Library         |
| State-Ort        | Bestehende `useChatSessions` erweitern | Kein neuer Hook, kein Prop-Drilling                    |

### Neue Pakete

| Paket            | Zweck                                                 |
| ---------------- | ----------------------------------------------------- |
| `react-markdown` | Markdown-Rendering in Nachrichtenblasen               |
| `remark-gfm`     | GitHub Flavored Markdown (Tabellen, Checkboxen, Code) |

---

## QA Test Results

**Tester:** QA Engineer (Claude)
**Test Date:** 2026-05-08
**Test Type:** Static code review + build verification (no live backend available — PROJ-30 still `In Progress`, PROJ-32 nginx-Routing noch `Planned`)
**Build Status:** `next build` PASS (TypeScript-Compile sauber, 0 Fehler)

### Scope-Hinweis

PROJ-30 (Backend) ist noch `In Progress` und PROJ-32 (nginx `/api/stream/`-Proxy) ist `Planned`. Ein End-to-End-Test gegen einen laufenden SSE-Endpunkt war daher nicht möglich. Diese QA bewertet die Frontend-Implementation gegen die Acceptance Criteria über eine **statische Code-Analyse + Build-Verifikation** und identifiziert Bugs, die ohne Live-Backend reproduzierbar sind. Eine zweite QA-Runde mit echtem Stream wird empfohlen, sobald PROJ-30 + PROJ-32 deployed sind.

### Acceptance Criteria — Test Matrix

#### Streaming-Rendering

| #   | AC                                            | Status | Evidenz                                                                                                                                                                                                                                                        |
| --- | --------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Tokens werden sofort eingefügt (kein Puffern) | PASS   | `streamChat()` parsed jedes `data:`-Event und ruft `onToken` synchron auf. `appendToken` macht ein granulares `setMessagesBySession`-Update mit Slice + In-Place-Replace (kein Re-Render der ganzen Liste) — siehe `useChatSessions.ts:266-277`                |
| 2   | Bubble wächst zeichenweise ohne Flackern      | PASS   | `MessageList` rendert Liste mit Index als Key, aber das spezifische Message-Objekt wird per ID aktualisiert. React reconciled nur die letzte Bubble. Streaming-Cursor ist CSS-only (`::after` + `animate-pulse`) — kein Flackern erwartet                      |
| 3   | Markdown bei partiellem Text korrekt          | PASS   | `react-markdown` toleriert unvollständige Syntax; Code-Renderer in `MessageBubble.tsx:15-41` differenziert Inline vs. Block. **HINWEIS:** Bei mitten im Codeblock abgebrochenem Text wird der Block bis zum Ende der Bubble interpretiert — visuell akzeptabel |
| 4   | Nach `[DONE]` ist Nachricht unveränderlich    | PASS   | `onDone` setzt `isStreaming=false`, `abortRef=null`. Keine weiteren Token-Updates möglich                                                                                                                                                                      |

#### Tool-Status-Anzeige

| #   | AC                                             | Status | Evidenz                                                                                  |
| --- | ---------------------------------------------- | ------ | ---------------------------------------------------------------------------------------- |
| 5   | `tool_start` zeigt Status-Chip                 | PASS   | `useChatSessions.ts:281-286` fügt zur `activeTools`-Liste hinzu (mit Dedup-Check)        |
| 6   | `tool_end` entfernt Chip                       | PASS   | `useChatSessions.ts:287-289` filtert Tool aus Liste                                      |
| 7   | Mehrere gleichzeitige Tools als separate Chips | PASS   | `ToolStatusChip` mappt über Array, jedes Tool eigenes `<div>` mit `key={tool}`           |
| 8   | HA-Tool zeigt tool-spezifisches Label          | PASS   | `TOOL_LABELS` + `TOOL_ICONS` in `ToolStatusChip.tsx:9-23` decken alle 5 Backend-Tools ab |

#### Stopp-Button

| #   | AC                                               | Status                                 | Evidenz                                                                                                                           |
| --- | ------------------------------------------------ | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 9   | Stopp-Button erscheint statt Send                | PASS                                   | `ChatInputArea.tsx:73-94` ternärer Render                                                                                         |
| 10  | Klick schließt SSE sofort                        | PASS                                   | `streamChat` nutzt `AbortController.abort()` — der `fetch()`-Request wird abgebrochen, Reader bricht aus der `while`-Schleife aus |
| 11  | Bis zum Abbruch empfangener Text bleibt sichtbar | PASS                                   | `stopStreaming` in `useChatSessions.ts:327-350` modifiziert nur die letzte Assistenten-Nachricht, behält `last.content`           |
| 12  | Nachricht erhält `[Abgebrochen]`-Tag             | PASS (mit Anmerkung — siehe Bug LOW-2) | `useChatSessions.ts:345-346` hängt `*[Abgebrochen]*` an. **Spec sagt** `[Abgebrochen]` ohne Italics                               |
| 13  | Eingabefeld nach Stopp wieder aktiv              | PASS                                   | `setIsStreaming(false)` in `stopStreaming`                                                                                        |

#### Eingabefeld-Verhalten

| #   | AC                                                      | Status | Evidenz                                                                            |
| --- | ------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------- |
| 14  | Während Streaming: disabled, Send hidden, Stopp visible | PASS   | `ChatInputArea.tsx:68` (`disabled={disabled                                        |  | isStreaming}`) + ternärer Button-Render |
| 15  | Rückkehr in Normalzustand bei Stream-Ende               | PASS   | `onDone` und `stopStreaming` setzen beide `isStreaming=false`                      |
| 16  | Enter während Streaming löst keine neue Anfrage aus     | PASS   | `ChatInputArea.tsx:42` `if (isStreaming) return;` direkt nach `e.preventDefault()` |

#### Fehlerbehandlung

| #   | AC                                                | Status | Evidenz                                                                                                                                                                                          |
| --- | ------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 17  | SSE-Verbindungsfehler → "Verbindung unterbrochen" | PASS   | `api.ts:336-340` catched `fetch`-Reject → `onError("Verbindung unterbrochen. Bitte erneut versuchen.")`. Reader-Fehler ebenfalls in `api.ts:426-432`                                             |
| 18  | `type:"error"` → Fehlermeldung in Bubble          | PASS   | `api.ts:414-419` ruft `onError`. `useChatSessions.ts:295-319` hängt Error-Bubble bei nicht-leerem partiellem Content separat an, sonst wandelt Placeholder in Error-Bubble. Sinnvolles Verhalten |
| 19  | HTTP 401 → Redirect zu /login                     | PASS   | `api.ts:343-347` `clearToken()` + `window.location.href = "/login"`                                                                                                                              |
| 20  | HTTP 429 → "Zu viele Anfragen"                    | PASS   | `api.ts:348-351`                                                                                                                                                                                 |

#### API-Service

| #   | AC                                                   | Status                 | Evidenz                                                                                                                                                                                              |
| --- | ---------------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 21  | `streamChat(sessionId, content, callbacks)`-Signatur | PASS                   | `api.ts:295-298` — entspricht der Tech-Design-Beschreibung, leicht abweichend zur Spec (Callbacks als Objekt statt einzelne Parameter — sauberer)                                                    |
| 22  | Funktion gibt `{ abort }` zurück                     | PASS                   | `api.ts:446`                                                                                                                                                                                         |
| 23  | Basis-URL konfigurierbar                             | PASS (aber andere Var) | **DOC-DRIFT:** Spec sagt `VITE_STREAM_API_URL`, Code nutzt `NEXT_PUBLIC_STREAM_API_URL`. Da das Projekt Next.js (nicht Vite) nutzt, ist `NEXT_PUBLIC_*` korrekt — Spec ist veraltet. Siehe Bug LOW-1 |
| 24  | JWT aus `localStorage` als `Authorization`-Header    | PASS                   | `api.ts:300, 329`                                                                                                                                                                                    |

#### Rückwärtskompatibilität

| #   | AC                                                                 | Status | Evidenz                                                                                                                                                 |
| --- | ------------------------------------------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 25  | Bestehende Session-Persistenz bleibt unverändert                   | PASS   | Sessions werden weiter über `fetchSessions`/`fetchSessionMessages`/`renameSessionApi`/`deleteSessionApi` verwaltet; keine Änderung an diesen Funktionen |
| 26  | Bestehende Sidebar/Auth bleiben unverändert                        | PASS   | `Sidebar.tsx`, `auth.ts`, `AuthContext` nicht angefasst                                                                                                 |
| 27  | Falls `STREAM_API_URL` nicht gesetzt → Fallback auf alten Endpunkt | PASS   | `useChatSessions.ts:409-412` wählt `streamingSend` vs `legacySend`. **Aber:** siehe Bug MED-1 zu Race-Condition                                         |

### Edge-Case Tests

| #           | Edge-Case                                                       | Status            | Notiz                                                                                                                                                                                                                                                    |
| ----------- | --------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| EC-1        | Stream bricht mitten im Wort ab                                 | PASS              | `appendToken` schreibt Strings ohne Word-Boundary-Logik; Partial-Word bleibt sichtbar                                                                                                                                                                    |
| EC-2        | Nutzer scrollt nach oben während Stream                         | FAIL              | **Bug HIGH-1:** `MessageList.tsx:35-37` macht bei jedem `messages`-Update unbedingt `scrollIntoView({behavior:"smooth"})` — Auto-Scroll wird **nicht deaktiviert**, wenn Nutzer nach oben scrollt. Nutzer wird bei jedem Token zum Bottom zurückgerissen |
| EC-3        | Sehr lange Antwort (>5000 Zeichen)                              | PASS (mit Risiko) | In-Place-Update vermeidet Re-Mount. **Risiko:** `react-markdown` re-parsed bei jedem Token den gesamten String — bei sehr langen Antworten + hoher Token-Frequenz potenziell merklich. Performance nicht messbar ohne Backend                            |
| EC-4        | Tool-Status erscheint, Stopp gedrückt                           | PASS              | `stopStreaming` setzt `setActiveTools([])`                                                                                                                                                                                                               |
| EC-5        | Mehrere Tabs senden gleichzeitig                                | PASS              | Jeder Tab hat eigenen `AbortController`; localStorage-Token wird geteilt aber nicht überschrieben                                                                                                                                                        |
| EC-6 (zus.) | Nutzer wechselt während Stream Session                          | FAIL              | **Bug HIGH-2:** Siehe unten                                                                                                                                                                                                                              |
| EC-7 (zus.) | Stream antwortet zu Session, die in Sidebar gelöscht wurde      | FAIL              | **Bug MED-2:** Siehe unten                                                                                                                                                                                                                               |
| EC-8 (zus.) | Nutzer sendet, wird vor 1. Token gelöscht (Tab-Close + Re-Open) | PASS              | Cleanup in `useChatSessions.ts:66-71` ruft `abortRef.current?.()`                                                                                                                                                                                        |

### Cross-Browser & Responsive

| Test           | Status                | Notiz                                                                                                                                  |
| -------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Chrome         | NICHT GETESTET (live) | Build kompiliert; alle APIs (`fetch.ReadableStream`, `AbortController`, `TextDecoder`) seit Chrome 76+                                 |
| Firefox        | NICHT GETESTET (live) | Alle APIs ab Firefox 102+ stabil                                                                                                       |
| Safari         | NICHT GETESTET (live) | **Risiko:** Safari 14- hatte historisch Probleme mit `ReadableStream` + langlebige `fetch`-Verbindungen. Safari 16+ sollte sicher sein |
| Mobile 375px   | NICHT GETESTET        | Tool-Chip-Container hat `flex-wrap gap-2` — sollte umbrechen. Stopp-Button 44×44 px erfüllt Touch-Target-Mindestmaß                    |
| Tablet 768px   | NICHT GETESTET        | Layout unverändert                                                                                                                     |
| Desktop 1440px | NICHT GETESTET        | Bubble-Maxwidth 70% — passt                                                                                                            |

### Security Audit (Red Team)

| #    | Test                                                   | Status          | Befund                                                                                                                                                                                                                                                                                                                                  |
| ---- | ------------------------------------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S-1  | JWT-Bypass mit fehlendem Token                         | PASS            | `streamChat` redirected zu `/login` wenn `getToken()` null ist (`api.ts:301-304`)                                                                                                                                                                                                                                                       |
| S-2  | JWT-Bypass durch leeren Token                          | PARTIAL         | `getToken()` returned `localStorage.getItem(...)` — leerer String wäre falsy. **Aber** ein gefälschter Bearer mit beliebigem Token wird vom Backend (PROJ-30) validiert. Frontend-seitig ok                                                                                                                                             |
| S-3  | XSS via Token im Markdown                              | PASS            | `react-markdown` ist standardmäßig sicher gegen Raw-HTML; keine `rehypeRaw`-Plugin geladen. Auch ein bösartiges Backend-Token mit `<script>` würde escaped                                                                                                                                                                              |
| S-4  | XSS via Tool-Status-Text                               | FAIL (low risk) | **Bug LOW-3:** `ToolStatusChip.tsx:46` rendert `evt.status` direkt in `<span>{label}</span>`. JSX escaped automatisch — also kein Code-Execution. **Aber:** Backend-kontrollierter String wird ungeprüft als Label angezeigt. Keine Sanitization. Da Backend auf JWT prüft und Backend-vertrauenswürdig ist: Risiko niedrig             |
| S-5  | Sensitive Daten in Console/Network                     | PASS            | Code logged keine Tokens. JWT erscheint nur im `Authorization`-Header (Standard)                                                                                                                                                                                                                                                        |
| S-6  | `session_id`-Manipulation (User-A liest User-B-Stream) | DEFER           | Frontend sendet `session_id` aus eigenem State. Authorization muss Backend (PROJ-30) prüfen — siehe AC dort. **Wichtig:** Frontend trustet `session_id` aus localStorage; ein manipulierter Client kann beliebige `session_id` senden. Backend MUSS bei jedem `/stream/chat`-Call prüfen, dass `session_id` zu `user_id` aus JWT gehört |
| S-7  | CSRF                                                   | PASS            | JWT-im-Authorization-Header (kein Cookie) → kein CSRF                                                                                                                                                                                                                                                                                   |
| S-8  | Speicherung der JWT in localStorage                    | KNOWN-RISK      | localStorage ist XSS-anfällig — aber bestehende Architektur (PROJ-7), nicht durch PROJ-31 verschlechtert                                                                                                                                                                                                                                |
| S-9  | `STREAM_API_URL` Open-Redirect                         | LOW             | Wenn `STREAM_API_URL` per Env auf einen externen Host zeigt, würde JWT dorthin gesendet. Nur für Admins, daher akzeptabel                                                                                                                                                                                                               |
| S-10 | Rate-Limiting auf Streaming-Endpoint                   | DEFER           | nginx Rate-Limit auf `/api/stream/` ist Teil von PROJ-32 — Frontend ist nicht zuständig                                                                                                                                                                                                                                                 |

### Regression Tests (Deployed Features)

| Feature                              | Status | Befund                                                                                         |
| ------------------------------------ | ------ | ---------------------------------------------------------------------------------------------- |
| PROJ-7 (JWT/Login)                   | PASS   | `auth.ts` unverändert, Token-Flow identisch                                                    |
| PROJ-8 (Sidebar/Landing)             | PASS   | `Sidebar.tsx` nicht geändert; `AppShell.tsx` ergänzt nur neue Props                            |
| PROJ-12 (Security/Rate-Limit/Rename) | PASS   | `renameSessionApi` weiter exportiert + genutzt                                                 |
| PROJ-14 (Sidebar Context-Menu)       | PASS   | Session-CRUD-Operationen unverändert                                                           |
| PROJ-26/27 (User Mgmt/Profile)       | PASS   | Settings-Routen nicht angefasst                                                                |
| Legacy non-streaming chat            | PASS   | `legacySend`-Pfad bleibt erhalten und wird genutzt, wenn `NEXT_PUBLIC_STREAM_API_URL` leer ist |

---

### Bugs Found

#### HIGH-1: Auto-Scroll überschreibt Nutzer-Scroll-Position während Streaming

**Datei:** `frontend/src/components/Chat/MessageList.tsx:35-37`
**Severity:** High (UX-blocker für lange Antworten)
**AC violated:** Edge Case "Nutzer scrollt während Stream nach oben → Auto-Scroll deaktiviert sich, ohne den Stream zu beeinflussen" (Spec Zeile 79)

**Steps to Reproduce:**
1. Stream eine sehr lange Antwort (>20 Zeilen)
2. Während des Streamings nach oben scrollen, um frühere Nachricht zu lesen
3. Bei jedem neuen Token wird die Liste **wieder ans Ende gescrollt** — Nutzer kann nicht im Verlauf lesen

**Erwartetes Verhalten:** Sobald Nutzer manuell nach oben scrollt, bleibt die Scroll-Position dort, bis der Nutzer wieder ans Ende scrollt.

**Lösungsansatz:** `IntersectionObserver` oder `scrollHeight` vs. `scrollTop+clientHeight` prüfen, ob Nutzer am Ende ist; nur dann auto-scrollen. (Implementierung Aufgabe der Frontend-Skill.)

---

#### HIGH-2: Session-Wechsel während Streaming bricht Stream nicht ab + sperrt neue Session

**Datei:** `frontend/src/hooks/useChatSessions.ts` (`selectSession`, `streamingSend`, `stopStreaming`)
**Severity:** High (Datenkorruption + UX-Block)

**Steps to Reproduce:**
1. Session A öffnen, Frage senden — Stream läuft
2. Während des Streams Session B in der Sidebar anklicken
3. Beobachte: 
   - `isStreaming` ist global → Eingabefeld in Session B ist disabled, Stopp-Button erscheint
   - Bei Klick auf Stopp: `stopStreaming` hängt `[Abgebrochen]`-Marker an die letzte Assistenten-Nachricht der **aktuell aktiven Session B** (`activeSessionId`), obwohl der Stream zu Session A gehört → **Falsche Session bekommt den Marker**
   - Tokens, die noch ankommen, werden weiter in Session A geschrieben (korrekt), aber `activeTools`-Chips erscheinen unter Session B

**Erwartetes Verhalten:** Entweder
- (a) Beim Session-Wechsel wird der Stream automatisch abgebrochen und Session A bekommt `[Abgebrochen]`, oder
- (b) Stream läuft im Hintergrund weiter, `isStreaming`/`activeTools` werden pro Session getrackt

**Code-Pfad-Beweis:**
```
useChatSessions.ts:337-349
  if (activeSessionId) {                     // <-- aktuelle (B), nicht Stream-Session (A)
    setMessagesBySession((prev) => {
      const current = prev[activeSessionId]; // <-- Bubbles aus Session B
      ...
      next[lastIdx] = { ...last, content: last.content + suffix };
```

---

#### MED-1: Race Condition bei Reaktivierung von `STREAM_API_URL` zur Laufzeit

**Datei:** `frontend/src/services/api.ts:10-11`
**Severity:** Medium (nur in dev, unwahrscheinlich in prod)

`STREAM_API_URL` wird beim Modul-Load **einmal** aus `process.env.NEXT_PUBLIC_STREAM_API_URL` gelesen. Das ist in Next.js korrekt (Env-Vars werden statisch gebunden), birgt aber das Risiko, dass nach einem Build-Wechsel ohne Hard-Reload alte/neue Werte koexistieren. Kein Bug im engeren Sinne, aber dokumentationswürdig.

---

#### MED-2: Stream antwortet zu Session, die der Nutzer in der Sidebar gelöscht hat

**Datei:** `frontend/src/hooks/useChatSessions.ts` (`deleteSession`, `appendToken`)
**Severity:** Medium

**Steps to Reproduce:**
1. Session A senden — Stream läuft
2. Während Stream: in Sidebar Session A per Context-Menu **löschen** (`deleteSession` filtert aus `sessions` raus, löscht `messagesBySession[A]`, erstellt neue Session, schaltet aktiv um)
3. Stream-Token kommen weiter an, `appendToken` versucht in `prev[A]` zu schreiben — Eintrag existiert nicht mehr, `current.length === 0` → `return prev` (no-op)
4. **Aber:** Der Stream wird nicht abgebrochen — `abortRef` zeigt weiter auf den laufenden Stream → unnötiger Netzwerktraffic, Backend speichert Antwort in eine bereits gelöschte Session (Geister-Daten in DB)

**Erwartetes Verhalten:** `deleteSession` sollte bei aktivem Stream auf dieser Session den Stream über `abortRef.current?.()` abbrechen.

---

#### MED-3: Race-Condition zwischen `onDone`/`onError` und `stopStreaming`

**Datei:** `frontend/src/hooks/useChatSessions.ts:290-294, 327-330`
**Severity:** Medium (selten reproduzierbar)

**Steps to Reproduce:**
1. Letztes Token kommt an, Backend sendet `[DONE]`
2. Nutzer drückt zur gleichen Zeit Stopp
3. Beide handlers laufen: `onDone` setzt `abortRef.current = null`. Dann (Microtask später) `stopStreaming` liest `abortRef.current` als `null` → `[Abgebrochen]`-Marker wird **nicht** gesetzt
4. Umgekehrt: `stopStreaming` läuft zuerst, danach (zu spät) `onDone` setzt `setIsStreaming(false)` erneut + cleart `activeTools` (kein Schaden)

**Auswirkung:** Erste Reihenfolge führt zu fehlendem `[Abgebrochen]`-Marker, obwohl Nutzer den Button gedrückt hat. Zweite Reihenfolge ist unkritisch. Klein, aber Verwirrungspotenzial.

---

#### LOW-1: Spec-Drift — Env-Var-Name divergiert zur Spec

**Datei:** `features/PROJ-31-frontend-streaming-ui.md` (Spec Zeile 68, 148) vs. `frontend/.env.example`, `frontend/src/services/api.ts:11`
**Severity:** Low

Spec nennt `VITE_STREAM_API_URL`, Code nutzt `NEXT_PUBLIC_STREAM_API_URL`. Da das Projekt Next.js (nicht Vite) verwendet, ist `NEXT_PUBLIC_*` technisch korrekt. **Empfehlung:** Spec aktualisieren, damit Doku/Code-Konsistenz besteht. (Kein Code-Fix, nur Spec-Update.)

---

#### LOW-2: `[Abgebrochen]`-Marker ist Italic-formatiert, Spec-Wortlaut weicht ab

**Datei:** `frontend/src/hooks/useChatSessions.ts:345`
**Severity:** Low (kosmetisch)

Code schreibt `*[Abgebrochen]*` (Markdown-Italic). Spec sagt nur `[Abgebrochen]`-Tag (Zeile 51). Da der Renderer Markdown unterstützt, wird das als kursiver Hinweis gerendert — sieht hübsch aus, aber Abweichung von Spec dokumentieren oder Spec anpassen.

---

#### LOW-3: Keine Längen-/Charakter-Validierung für `tool_status`-Strings

**Datei:** `frontend/src/components/Chat/ToolStatusChip.tsx:46`
**Severity:** Low

Backend-gelieferter `status`-String wird unbeschnitten als Chip-Label angezeigt. Ein bösartiges Backend könnte einen 10-MB-String senden → Layout-Crash. Da Backend (PROJ-30) JWT-geschützt und vertrauenswürdig ist: niedriges Risiko. **Empfehlung:** Truncate auf z.B. 80 Zeichen via `text-ellipsis`/`max-w-[20ch]`.

---

#### LOW-4: `aria-live`-Region für Token-Stream fehlt

**Datei:** `frontend/src/components/Chat/MessageBubble.tsx:78-89`
**Severity:** Low (Accessibility)

Streaming-Bubble hat keinen `aria-live="polite"`-Marker. Screenreader-Nutzer bekommen einzelne Token nicht angesagt — entweder die ganze Liste pollen oder gar nichts. Best Practice für Live-Streams: `aria-live="polite"` + `aria-atomic="false"` auf der wachsenden Bubble. `MessageList` hat `role="log"`, was teilweise hilft.

---

#### LOW-5: Cleanup-`useEffect` hat leere Deps + abortRef-Reset bei Re-Mount

**Datei:** `frontend/src/hooks/useChatSessions.ts:66-71`
**Severity:** Low (theoretisch, mit StrictMode bemerkbar)

In React 19 + StrictMode wird der Cleanup beim ersten Mount in dev synthetisch ausgeführt. Das ruft `abortRef.current?.()` auf, was bei einem laufenden Stream den Stream abbrechen würde. Allerdings ist beim ersten Mount `abortRef.current` immer `null` → kein Effekt. Code ist korrekt, aber wert zu kennen.

---

### Bug-Zusammenfassung

| Severity | Anzahl | IDs                               |
| -------- | ------ | --------------------------------- |
| Critical | 0      | —                                 |
| High     | 2      | HIGH-1, HIGH-2                    |
| Medium   | 3      | MED-1, MED-2, MED-3               |
| Low      | 5      | LOW-1, LOW-2, LOW-3, LOW-4, LOW-5 |

### Production-Ready Decision

**NOT READY** — 2 High-Severity-Bugs (HIGH-1, HIGH-2) müssen vor dem Deploy behoben werden:

- **HIGH-1** verletzt einen explizit gelisteten Edge-Case der Spec und macht das Feature für lange Antworten unbrauchbar.
- **HIGH-2** führt zu inkonsistentem UI-State (`[Abgebrochen]` an falscher Session) und kann je nach Backend-Verhalten zu Daten-Inkonsistenzen führen.

Die Medium-Bugs (MED-2 insbesondere) sollten priorisiert werden, sind aber nicht zwingend Deploy-Blocker.

### Empfohlene Reihenfolge der Fixes

1. **HIGH-1** (Auto-Scroll) — Frontend-Skill, kleine Änderung in `MessageList.tsx`
2. **HIGH-2** (Session-Wechsel + Stream) — Frontend-Skill, Entscheidung treffen ob abort-on-switch oder per-session-state
3. **MED-2** (Stream nach Session-Delete) — `deleteSession` ruft `abortRef.current?.()` wenn deleted == streaming-session
4. **MED-3** (Race onDone/stopStreaming) — `stopStreaming` defensiver: setze Marker auch wenn `abortRef` schon null ist und letzte Nachricht eine leere/streaming Bubble ist
5. **LOW-1** (Spec-Drift) — Spec aktualisieren auf `NEXT_PUBLIC_STREAM_API_URL`
6. **LOW-2 - LOW-5** — optional vor Deploy oder als Followup

### Nächste Schritte

Nach Behebung der High-Bugs:
- Re-Test mit laufendem PROJ-30-Backend und PROJ-32-nginx-Routing
- Manueller Cross-Browser-Test (Chrome, Firefox, Safari)
- Manueller Responsive-Test (375px, 768px, 1440px)
- Performance-Messung mit langer (>5000 Char) Antwort

