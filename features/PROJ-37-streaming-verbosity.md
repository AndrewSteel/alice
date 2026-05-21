# PROJ-37: Streaming Verbosity — Thinking-Support und angereicherte Tool-Events

**Status:** In Review
**Created:** 2026-05-13
**Last Updated:** 2026-05-13

## Kontext & Motivation

Das Chat-Frontend (PROJ-35) hat einen `thinking`-Renderer bereits vorbereitet und ein vollständiges Rollen-Datenmodell (`tool_call`, `thinking`, `assistant`). Das Backend (`alice-chat-stream`, PROJ-30) liefert jedoch noch nicht:

- **Kein Thinking-Stream**: `think: False` ist hardcoded in `streaming.py:79`. Das Modell (qwen3:14b) denkt intern, aber die Reasoning-Tokens werden nicht an den Client gesendet.
- **Statischer Tool-Status**: `TOOL_STATUS_TEXT` ist ein fixer Dict mit generischen Texten (z.B. "Suche in Dokumenten…"), unabhängig von der konkreten Suchanfrage.
- **Leeres tool_end**: Das `tool_end`-Event hat kein Ergebnis-Feedback (z.B. "3 Dokumente gefunden").
- **Frontend ohne thinking-Handler**: `useChatSessions.ts` hat keinen Handler für `thinking`-SSE-Events; die vorbereitete `ThinkingMessage.tsx` wird nie gerendert.

## Dependencies

- Requires: PROJ-30 (alice-chat-stream Backend)
- Requires: PROJ-35 (Chat Frontend Redesign — Datenmodell, ThinkingMessage.tsx)
- Ollama-Doku: https://docs.ollama.com/capabilities/thinking

## User Stories

- Als Nutzer möchte ich sehen, was Alice gerade denkt (z.B. "Ich muss prüfen, ob das eine Frage zum Dokument ist…"), damit die Antwortqualität für mich nachvollziehbar wird.
- Als Nutzer möchte ich beim Tool-Aufruf den konkreten Suchbegriff sehen (z.B. "Suche nach 'Rechnung November 2025'…" statt nur "Suche in Dokumenten…"), damit ich sofort erkennen kann, ob Alice meine Anfrage richtig verstanden hat.
- Als Nutzer möchte ich nach einem Tool-Aufruf eine kurze Ergebnis-Rückmeldung sehen (z.B. "4 Dokumente gefunden"), damit ich weiß, ob die Suche erfolgreich war, bevor die Antwort erscheint.
- Als Andreas (Entwickler) möchte ich, dass Thinking-Tokens aus dem Ollama-Stream direkt weitergeleitet werden, ohne LLM-Latenz zu erhöhen, damit das Feature die Antwortzeit nicht verschlechtert.

## Acceptance Criteria

### Backend: Thinking-Stream

- [ ] `think: True` ist in der Ollama-Anfrage gesetzt (statt `False`)
- [ ] Chunks mit `message.thinking` werden als SSE-Event `{"type":"thinking","content":"..."}` gesendet
- [ ] Thinking-Tokens und Text-Tokens sind strikt getrennt: `message.thinking` → `thinking`-Event, `message.content` → `token`-Event
- [ ] Thinking-Tokens werden **nicht** in `accumulated_text` aufgenommen (die gespeicherte Assistenten-Antwort in `alice.messages` enthält nur den finalen Text)
- [ ] Thinking-Tokens werden **nicht** in der Prometheus-Metrik `chat_tokens_total` gezählt (oder alternativ in einer separaten Metrik)
- [ ] Der Thinking-Stream erscheint vor dem ersten `token`-Event (Ollama-Verhalten: thinking first, then content)

### Backend: Angereicherte Tool-Events

**tool_start:**
- [ ] `status`-Text ist dynamisch und enthält die konkrete Anfrage aus den Tool-Argumenten:
  - `search_documents(query=...)` → `"Suche nach '{{query}}'…"`
  - `get_document_details(document_id=...)` → `"Lade Dokument {{document_id}}…"`
  - `home_assistant(command=...)` → `"Smart Home: {{command}}…"`
  - `recall(query=...)` → `"Erinnere mich an '{{query}}'…"`
  - `remember(fact=...)` → `"Merke: '{{fact}}'…"`
  - Fallback (unbekannte Tools): `"Führe {{tool_name}} aus…"`
- [ ] `status`-Text ist auf 80 Zeichen begrenzt (Truncate mit `…`)

**tool_end:**
- [ ] Event enthält ein optionales `summary`-Feld mit einer kurzen deutschen Ergebnis-Zusammenfassung:
  - `search_documents` OK → `"{{n}} Dokument(e) gefunden"` (n aus dem Ergebnis)
  - `search_documents` leer → `"Keine Dokumente gefunden"`
  - `home_assistant` OK → `"Ausgeführt"`
  - `home_assistant` Fehler → `"Fehler: {{error_message}}"` (auf 60 Zeichen begrenzt)
  - `remember` / `recall` OK → `"Gespeichert"` / `"{{n}} Erinnerung(en) gefunden"`
  - Fehlerfall allgemein → `"Fehler"`
- [ ] `summary` ist optional; fehlt es, bleibt das Frontend-Verhalten unverändert

### Frontend: Thinking-Event-Handling

- [ ] `useChatSessions.ts` hat einen Handler für SSE-Event-Typ `thinking`
- [ ] Erstes `thinking`-Event in einem Turn: fügt eine neue `Message` mit `role: 'thinking'` und `streaming: true` in die Nachrichtenliste ein
- [ ] Folgende `thinking`-Events desselben Turns: Inhalt wird an die letzte `thinking`-Nachricht angehängt (`appendToken`-Logik)
- [ ] Erstes `token`-Event nach einem Thinking-Block: fügt eine neue `Message` mit `role: 'assistant'` ein (kein Append auf die `thinking`-Nachricht)
- [ ] `done`-Event setzt `streaming: false` auf der letzten aktiven Nachricht — funktioniert bereits für `assistant` und muss auch für `thinking` gelten (für den Fall, dass nur Thinking ohne Token kommt)
- [ ] `ThinkingMessage.tsx` wird gerendert (war vorbereitet, aber nie aktiviert)

### Frontend: tool_end mit summary

- [ ] Wenn `tool_end.summary` vorhanden: `content` der passenden `tool_call`-Nachricht wird auf `summary` gesetzt
- [ ] Wenn `tool_end.summary` fehlt: bisheriges Verhalten (nur `toolStatus` auf `'done'` setzen)

## Edge Cases

- Ollama sendet `message.thinking` und `message.content` im selben Chunk → beide werden korrekt als separate Events gesendet (thinking zuerst)
- Thinking-Text ist sehr lang (>5000 Tokens) → wird trotzdem vollständig gestreamt; kein Abschneiden auf Backend-Seite
- Tool wird innerhalb eines Thinking-Blocks aufgerufen (theoretisch) → `tool_start` unterbricht den Thinking-Stream; `tool_end` wird gesendet; Thinking kann danach weitergehen oder `token`-Events folgen
- `remember(fact=...)` hat einen sehr langen Fakt → `status`-Text auf 80 Zeichen begrenzt mit `…`
- `home_assistant` gibt kein `command`-Feld zurück → Fallback auf `"Steuere Smart Home…"`
- Nutzer bricht während Thinking-Phase ab (Stopp-Button) → `markStreamAborted` muss auch offene `thinking`-Nachricht mit `streaming: false` schließen (analog zu `tool_call` BUG-1 aus PROJ-35)
- `search_documents` gibt leere Liste zurück → `summary: "Keine Dokumente gefunden"` statt "0 Dokumente gefunden"

## Datenmodell: SSE-Event-Erweiterungen

```
Bestehend (unverändert):
  data: {"type":"token","content":"..."}
  data: {"type":"tool_start","tool":"...","status":"...","query":"..."}
  data: {"type":"tool_end","tool":"...","ok":true}
  data: {"type":"error","message":"..."}
  data: {"type":"done","usage":{...}}
  data: [DONE]

Neu (PROJ-37):
  data: {"type":"thinking","content":"..."}          ← NEU: Reasoning-Token

Geändert (PROJ-37):
  data: {"type":"tool_start","tool":"search_documents","status":"Suche nach 'Rechnung November'…","query":"Rechnung November"}
  data: {"type":"tool_end","tool":"search_documents","ok":true,"summary":"3 Dokumente gefunden"}
```

Mapping SSE → MessageRole (Ergänzung zu PROJ-35):

| SSE-Event | Aktion |
|---|---|
| `thinking` | Append auf letzte `thinking`-Nachricht; oder neue `thinking`-Nachricht einfügen wenn letzte nicht `thinking` ist |
| `token` (nach thinking) | Neue `assistant`-Nachricht einfügen, dann Append |
| `tool_end` mit `summary` | `toolStatus: 'done'` setzen + `content` auf `summary` aktualisieren |

## Scope-Abgrenzung

**In Scope:**
- `docker/compose/automations/alice-chat-stream/app/streaming.py` — think aktivieren, Tool-Events anreichern, Thinking-Events emittieren
- `frontend/src/hooks/useChatSessions.ts` — Thinking-Event-Handler, tool_end summary-Handling, Abort-Fix für thinking-Nachrichten

**Out of Scope:**
- System-Prompt-Anpassungen (Modell-Anweisungen, wie viel es denken soll)
- Thinking-Tokens in `alice.messages` persistieren
- Neues `thinking`-Feld in `alice.messages` (Datenbankschema bleibt unverändert)
- Neue Prometheus-Metrik für Thinking-Tokens (optional, kann nachgezogen werden)
- `ThinkingMessage.tsx` visuelles Design (bereits in PROJ-35 implementiert)

---

## Tech Design (Solution Architect)

### Scope: Drei Dateien, keine neuen Services

PROJ-37 ist eine reine Code-Erweiterung. Kein neuer Container, keine neue Datenbank-Tabelle, keine neuen API-Endpunkte.

```
BACKEND
  docker/compose/automations/alice-chat-stream/app/streaming.py
    ↑ einzige Datei mit Backend-Änderungen

FRONTEND
  frontend/src/services/api.ts            ← SSE-Parser erweitern
  frontend/src/hooks/useChatSessions.ts   ← State-Management erweitern
```

`ThinkingMessage.tsx` ist bereits deployt (PROJ-35) und muss nicht angefasst werden.

---

### Bereich 1 — Backend: `streaming.py`

#### 1a. Thinking aktivieren

Die Ollama-Anfrage bekommt `"think": True`. Ollama liefert daraufhin im Stream zwei Felder:
- `message.thinking` — Reasoning-Tokens (kommen zuerst)
- `message.content` — Antwort-Tokens (kommen danach)

Der bestehende Loop liest bisher nur `message.content`. Er muss um die Prüfung von `message.thinking` erweitert werden:

```
Für jeden Chunk aus dem Ollama-Stream:
  hat message.thinking? → SSE thinking-Event senden
  hat message.content?  → SSE token-Event senden (unverändert)
```

**Wichtig:** Thinking-Tokens werden nicht in `accumulated_text` aufgenommen. Nur der finale Antworttext landet in `alice.messages`. Thinking ist flüchtig.

Optional: Env-Var `OLLAMA_THINK` (default: `true`). Damit kann Thinking bei Bedarf deaktiviert werden, ohne Code-Änderung.

#### 1b. Angereicherte `tool_start`-Status-Texte

Statt statischem Dict wird der Status-Text dynamisch aus den Tool-Argumenten gebaut:

| Tool | Argument | Ergebnis-Text |
|---|---|---|
| `search_documents` | `query="Rechnung Nov"` | `"Suche nach 'Rechnung Nov'…"` |
| `get_document_details` | `weaviate_id="abc123"` | `"Lade Dokument abc123…"` |
| `home_assistant` | `command="Licht an"` | `"Smart Home: Licht an…"` |
| `recall` | `query="Lieblingsessen"` | `"Erinnere mich an 'Lieblingsessen'…"` |
| `remember` | `key="x"`, `value="y"` | `"Merke: x = y…"` |
| Fallback | — | `"Führe {tool_name} aus…"` |

Alle Texte werden auf 80 Zeichen begrenzt (Truncate mit `…`).

#### 1c. `tool_end` mit Ergebnis-Zusammenfassung

Nach Rückkehr des Tool-Ergebnisses wird ein `summary`-Text erzeugt und im `tool_end`-Event mitgeschickt:

| Tool | Ergebnis | Summary-Text |
|---|---|---|
| `search_documents` | 3 Treffer | `"3 Dokumente gefunden"` |
| `search_documents` | 0 Treffer | `"Keine Dokumente gefunden"` |
| `home_assistant` | OK | `"Ausgeführt"` |
| `home_assistant` | Fehler | `"Fehler: {error}"` (auf 60 Zeichen) |
| `remember` | OK | `"Gespeichert"` |
| `recall` | N Treffer | `"N Erinnerung(en) gefunden"` |
| beliebig | Fehler | `"Fehler"` |

Das `summary`-Feld ist optional — fehlt es, bleibt das Frontend-Verhalten unverändert.

---

### Bereich 2 — Frontend: `api.ts`

Aktuell kennt der SSE-Parser folgende Event-Typen: `token`, `tool_start`, `tool_end`, `error`, `done`.

**Zwei Erweiterungen:**

1. Neuer Case `"thinking"` → ruft `callbacks.onThinking(content)` auf  
2. `"tool_end"` → übergibt jetzt auch `evt.summary` an `callbacks.onToolEnd(tool, summary)`

Die `StreamCallbacks`-Schnittstelle bekommt:
- `onThinking: (content: string) => void` — NEU
- `onToolEnd`: Signatur erweitert um optionales `summary?: string`

---

### Bereich 3 — Frontend: `useChatSessions.ts`

Vier kleine Erweiterungen am bestehenden Hook:

#### 3a. `handleThinking` (NEU)

Wird bei jedem `thinking`-Event aufgerufen:

```
Ist das letzte Objekt in der Nachrichtenliste ein leerer assistant-Platzhalter?
  JA  → in-place umwandeln zu thinking-Nachricht, content setzen
  NEIN, letzte ist already "thinking"?
        → content anhängen
  SONST → neue thinking-Nachricht einfügen
```

Dieser Ansatz stellt sicher, dass der leere `assistant`-Platzhalter (den `streamingSend` sofort einfügt) elegant zu einem `thinking`-Block wird — ohne Extra-Leerzeile im Chat.

#### 3b. `appendToken` — Thinking→Token-Übergang

Der bestehende Code behandelt `assistant` und `thinking` gleich (beide: content anhängen). Das ist falsch wenn `token`-Events nach `thinking`-Events kommen — dann würden Reasoning-Text und Antwort-Text in derselben Nachricht landen.

Neue Logik:

```
Letzte Nachricht ist "assistant"? → content anhängen (unverändert)
Letzte Nachricht ist "thinking"?  → Thinking schließen (streaming=false),
                                     neue assistant-Nachricht einfügen
Letzte Nachricht ist was anderes? → neue assistant-Nachricht (unverändert)
```

#### 3c. `handleToolEnd` — Summary übernehmen

Wenn `summary` vorhanden: `content` der passenden `tool_call`-Nachricht auf `summary` setzen. Kein `summary`? Nur `toolStatus → 'done'` wie bisher.

#### 3d. `markStreamAborted` — Thinking-Nachrichten schließen

Beim Stopp-Button: alle offenen `thinking`-Nachrichten (`streaming: true`) müssen `streaming: false` bekommen (analog zur bestehenden Behandlung von `tool_call`-Nachrichten aus PROJ-35 BUG-1).

---

### Datenhaltung

Keine Änderung. Thinking-Tokens werden **nicht** persistiert.

| Was | Verhalten |
|---|---|
| `alice.messages.content` | Nur finaler Antworttext (unverändert) |
| `alice.messages.tool_calls` | Tool-Name + Argumente (unverändert) |
| Thinking-Text | Nur in-session im React-State, verschwindet nach Reload |

---

### Abhängigkeiten (keine neuen Pakete)

Keine neuen Python- oder npm-Pakete. Alle Änderungen nutzen bestehende Bibliotheken und APIs.

---

### SSE-Datenfluss (Zusammenfassung)

```
Ollama (think:true)
  └─ message.thinking  →  data: {"type":"thinking","content":"..."}   ← NEU
  └─ message.content   →  data: {"type":"token","content":"..."}      [unverändert]

tool_start (vorher):  {"type":"tool_start","tool":"...","status":"Suche in Dokumenten…"}
tool_start (nachher): {"type":"tool_start","tool":"...","status":"Suche nach 'Rechnung Nov'…"}

tool_end (vorher):  {"type":"tool_end","tool":"...","ok":true}
tool_end (nachher): {"type":"tool_end","tool":"...","ok":true,"summary":"3 Dokumente gefunden"}

api.ts:
  case "thinking" → onThinking(content)   ← NEU
  case "tool_end" → onToolEnd(tool, summary)  ← erweitert

useChatSessions.ts:
  handleThinking   → push / konvertiere / appende thinking-Nachricht  ← NEU
  appendToken      → Thinking→Token-Übergang korrekt behandeln        ← geändert
  handleToolEnd    → summary optional in tool_call.content setzen     ← erweitert
  markStreamAborted → thinking-Nachrichten beim Abort schließen       ← erweitert
```

## QA Test Results

**Tested:** 2026-05-13
**Tester:** /qa (Claude)
**Build state:** Code committed locally; Backend (`alice-chat-stream`) und Frontend wurden NICHT deployed. Tests laufen ausschliesslich auf statischer Analyse, AST-Parsing, `tsc --noEmit` und zwei Test-Harnessen:
- Python: Stubbed Ollama + Stubbed tools, exercises `streaming.py:stream_chat()` als async generator.
- Node/JS: Re-Implementation der State-Transitions aus `useChatSessions.ts` zum deterministischen Tracen der Message-List.

### Acceptance-Criteria-Matrix

#### Backend: Thinking-Stream

| # | Kriterium | Ergebnis | Beleg |
|---|---|---|---|
| B1 | `think: True` in Ollama-Anfrage statt `False` | PASS | `streaming.py:198` sendet `"think": OLLAMA_THINK`; Default `OLLAMA_THINK=True`. Harness Test 3 zeigt `Sent payload think field: True/False` |
| B2 | `message.thinking`-Chunks → SSE `thinking`-Event | PASS | `streaming.py:230-232`. Harness E2E-Trace zeigt `{"type":"thinking",...}`-Events |
| B3 | Thinking- und Text-Tokens strikt getrennt | PASS | Im selben Chunk werden `thinking` und `content` als ZWEI separate SSE-Events (in dieser Reihenfolge) emittiert. Harness Test 1 (thinking+content im selben Chunk) bestätigt: 4 Events fuer 2 Chunks |
| B4 | Thinking NICHT in `accumulated_text` | PASS | `streaming.py:236-237` addiert nur `content` zu `accumulated_text`. Harness side-effect: `final_text` enthielt nur Antwort-Text |
| B5 | Thinking NICHT in `chat_tokens_total` | PASS | `metrics.CHAT_TOKENS_TOTAL.inc()` nur in Zeile 238 (content-Pfad). Harness zaehlte korrekt 3 Tokens fuer 3 Content-Chunks, 0 fuer 3 Thinking-Chunks |
| B6 | Thinking erscheint VOR erstem `token` | PASS | `streaming.py:227` (thinking) wird VOR `:234` (content) ausgewertet — Reihenfolge im Code garantiert. Harness Test 1 zeigt Reihenfolge `thinking, token, thinking, token, ...` |

#### Backend: Angereicherte `tool_start`

| # | Kriterium | Ergebnis | Beleg |
|---|---|---|---|
| TS1 | `search_documents(query=...)` → `"Suche nach '{query}'…"` | PASS | `_build_tool_status` Zeile 72-76. Harness: `"Suche nach 'Rechnung November 2025'…"` |
| TS2 | `get_document_details(weaviate_id=...)` → `"Lade Dokument {id}…"` | PASS | Zeile 78-85. Beachte: Spec nennt `document_id`, Code akzeptiert BEIDE (`weaviate_id` UND `document_id`). Gut. |
| TS3 | `home_assistant(command=...)` → `"Smart Home: {cmd}…"` | PASS | Zeile 87-91. Harness: `"Smart Home: Wohnzimmerlicht einschalten…"` |
| TS4 | `recall(query=...)` → `"Erinnere mich an '{query}'…"` | PASS | Zeile 93-97 |
| TS5 | `remember(fact=...)` → `"Merke: '{fact}'…"` | PASS (mit Anmerkung) | Code priorisiert `key+value` → `"Merke: {key} = {value}…"`, faellt sonst auf `fact` zurueck. Spec listet nur `fact`; aber der Tool-Schema (`tools.py:91`) deklariert `key+value` als Parameter. Die Implementation deckt damit den tatsaechlichen Aufruf-Pfad ab. |
| TS6 | Fallback `"Führe {tool_name} aus…"` | PASS | Zeile 110. Harness: `"Führe unknown_tool aus…"` |
| TS7 | Status auf 80 Zeichen begrenzt, Truncate mit `…` | PASS | `_truncate` reserviert 1 Char fuer das Ellipsis-Zeichen. Harness mit 200-Char-Query: `len=80` |

#### Backend: Angereicherte `tool_end`

| # | Kriterium | Ergebnis | Beleg |
|---|---|---|---|
| TE1 | `search_documents` OK → `"{n} Dokument(e) gefunden"` | PASS | Zeile 142-146. Harness: 3 hits → `"3 Dokumente gefunden"`; 1 hit → `"1 Dokument gefunden"` (Singular korrekt). |
| TE2 | `search_documents` leer → `"Keine Dokumente gefunden"` | PASS | Edge-Case-Bullet erfuellt; Harness Test 2 |
| TE3 | `home_assistant` OK → `"Ausgeführt"` | PASS | Zeile 157-158 |
| TE4 | `home_assistant` Fehler → `"Fehler: {error}"` auf 60 Zeichen | PASS | Zeile 134-137: `_truncate(err, TOOL_ERROR_DETAIL_MAX_LEN=60)`, dann outer-truncate auf 80. Detail-Portion misst 59 Chars + `…` = 60 (spec-konform) |
| TE5 | `remember` OK → `"Gespeichert"` | PASS | Zeile 154-155 |
| TE6 | `recall` N → `"N Erinnerung(en) gefunden"` | PASS | Singular/Plural korrekt: 1 → "Erinnerung", 2 → "Erinnerungen" |
| TE7 | Allgemeiner Fehler → `"Fehler"` | PASS | Zeile 140 (ok=False, kein `error`-Feld) |
| TE8 | `summary` ist optional; fehlt es, FE-Verhalten unverändert | PASS | `streaming.py:336-337` schickt das Feld nur wenn nicht-leer; api.ts:426 reicht `evt.summary` (potentiell undefined) durch; useChatSessions.ts:443 behaelt `m.content`, wenn `summary` falsy |

**Bonus (nicht in Spec aber implementiert):**
- `get_document_details` OK → `"Geladen"` (Zeile 160-161). Sinnvoll, kein Konflikt.
- `recall` leer → `"Keine Erinnerungen gefunden"` (analog zu `search_documents`). Sinnvoll.
- Timeout → `"Fehler: Zeitüberschreitung"` (Zeile 138-139). Sinnvoll.

#### Frontend: Thinking-Event-Handling

| # | Kriterium | Ergebnis | Beleg |
|---|---|---|---|
| FT1 | `useChatSessions.ts` hat Handler fuer `thinking` | PASS | `appendThinking` Zeile 364-396; `streamChat`-Callback Zeile 520 |
| FT2 | Erstes Thinking-Event: neue `thinking`-Message mit `streaming: true` | PASS (mit Verbesserung) | Code konvertiert den leeren `assistant`-Platzhalter IN-PLACE zu `thinking` (Zeile 372-381). Das ist BESSER als die Spec-Vorgabe ("fügt eine neue Message ein"), weil es den Platzhalter eliminiert. Harness Test 1 bestaetigt. |
| FT3 | Folgende Thinking-Events: Content anhaengen | PASS | Zeile 383-384 |
| FT4 | Erstes `token`-Event nach Thinking-Block: neue `assistant`-Message | PASS | `appendToken` Zeile 342-356: wenn `last.role === "thinking"`, wird `streaming: false` gesetzt und eine neue assistant-Message angelegt. Harness Test 1 bestaetigt. |
| FT5 | `done`-Event setzt `streaming: false` auf der letzten aktiven Nachricht (inkl. thinking) | PASS | `finishStream` Zeile 462-468 sucht von hinten nach der ersten `streaming: true`-Message und setzt das Flag. Funktioniert generisch fuer `assistant` UND `thinking`. Harness Test 7 (pure-thinking turn) bestaetigt. |
| FT6 | `ThinkingMessage.tsx` wird gerendert | PASS | `MessageRenderer.tsx:27-28` rendert `thinking`-Rolle. Datei existiert seit PROJ-35. |

#### Frontend: `tool_end` mit summary

| # | Kriterium | Ergebnis | Beleg |
|---|---|---|---|
| FE1 | `summary` vorhanden → `content` der `tool_call`-Nachricht wird ueberschrieben | PASS | `handleToolEnd` Zeile 440-444. Harness Test 2: `tool_call` Content geht von `"Suche nach 'Rechnung'…"` zu `"3 Dokumente gefunden"`. |
| FE2 | `summary` fehlt → bisheriges Verhalten | PASS | `summary && summary.length > 0 ? summary : m.content` — bei fehlender summary bleibt m.content unveraendert. Harness Test 3. |

#### Edge Cases (alle aus Spec-Sektion "Edge Cases")

| # | Edge Case | Ergebnis | Beleg |
|---|---|---|---|
| EC1 | Ollama sendet `thinking` und `content` im SELBEN Chunk → beide korrekt als separate Events, thinking zuerst | PASS | Harness Test 1 zeigt: Chunk `{thinking:"Hmm,", content:"Hallo"}` → emittiert `thinking` THEN `token`. Reihenfolge garantiert durch Code-Reihenfolge in `streaming.py:227-239`. |
| EC2 | Thinking-Text >5000 Tokens wird vollstaendig gestreamt | PASS | Keine Bound im Code; jeder Chunk wird unbegrenzt durchgereicht (`thinking = msg.get("thinking") or ""` ohne Truncate). |
| EC3 | Tool innerhalb eines Thinking-Blocks → `tool_start` unterbricht, danach kann Thinking weitergehen | PASS | Harness Test 8: `thinking → tool1 → thinking → tool2 → token` ergibt korrekt 5 Bubbles (Thinking-A, Tool-1, Thinking-B, Tool-2, Assistant). `handleToolStart` schliesst auch offene Thinking-Bubbles (Zeile 405-411). |
| EC4 | `remember(fact=...)` mit sehr langem Fakt → status auf 80 Zeichen | PASS | Harness: `"Merke: k = VVV…"` truncated auf 80 |
| EC5 | `home_assistant` ohne `command` → Fallback `"Steuere Smart Home…"` | PASS | Zeile 91 |
| EC6 | Nutzer bricht waehrend Thinking ab → `markStreamAborted` schliesst offene thinking-Nachricht | PASS | Zeile 132-135 setzt `streaming: false`. Harness Test 4: nach Abort hat `thinking`-Bubble kein `[streaming]`-Flag mehr. |
| EC7 | `search_documents` leer → `"Keine Dokumente gefunden"` statt `"0 Dokumente gefunden"` | PASS | Zeile 144-145 (`n is None or n <= 0`) |

### Cross-Browser / Responsive

Nicht ausgefuehrt — Frontend wurde nicht deployed; lokale `npm run dev`-Tests wurden auf Anweisung nicht durchgefuehrt. Da PROJ-37 ausschliesslich Logik-Code (kein neues CSS, kein neuer Layout-Code) hinzufuegt und sich auf bereits in PROJ-35 deployte Renderer (`ThinkingMessage.tsx`, `ToolCallMessage.tsx`) stuetzt, ist das Visual-Regressionsrisiko niedrig. Empfehlung: nach Deploy stichprobenartig Chrome + Firefox + iPad-Breite testen.

### Security Audit (Red Team)

| Vektor | Befund |
|---|---|
| **Auth-Bypass** | `main.py:128` setzt `user_id` ausschliesslich aus dem verifizierten JWT-Payload. `verify_jwt` wurde nicht angefasst. Keine Regression. |
| **XSS via Thinking-Content** | `ThinkingMessage.tsx:27` rendert `{content}` als React-Textnode. React escapiert HTML automatisch. KEIN Risiko. |
| **XSS via Tool-Status / Summary** | `ToolCallMessage.tsx:41` rendert `{label}` (= `content`) als React-Textnode. Bei `summary="<img onerror=...>"` (theoretisch durch n8n-Antwort steuerbar) wird der String ESCAPIERT angezeigt. KEIN Risiko. |
| **Injection via `query` in `tool_start.status`** | Der dynamische Status-Text enthaelt die User-Query nur als Display-Text — keine SQL-/Shell-Interpolation. Frontend rendert als Text. SAFE. |
| **PII-Leak in Logs** | `streaming.py` loggt KEINE Thinking-Chunks. `body[:500]` (Ollama-Error) und `line[:200]` (Parse-Error) sind die einzigen Logging-Pfade, die User-Content beruehren koennen — beide existieren bereits seit PROJ-30. Keine Regression. |
| **PII-Persistenz** | Thinking wird NICHT in `alice.messages` gespeichert (`accumulated_text` enthaelt nur Content). Compliance OK. |
| **Authorization (per-User-Tool-Calls)** | `user_id` wird aus JWT in `execute_tool` weitergereicht (`streaming.py:303`). RLS/Permission-Checks in n8n Sub-Workflows liegen ausserhalb des Scopes von PROJ-37. Keine Aenderung. |
| **Rate-Limiting** | Keine Aenderung am nginx- oder FastAPI-Layer. Bestehende Limits gelten weiterhin. |
| **CSRF / SSE-Endpunkt** | Token-Header-Auth (Bearer) — kein Cookie-Auth, daher CSRF-immun. Keine Aenderung. |
| **Tokens-Counter-Manipulation** | Da Thinking-Tokens NICHT in `CHAT_TOKENS_TOTAL` zaehlen, kann ein boesartiges Modell die Metrik durch endlose Thinking-Streams NICHT inflationieren — gutes Verhalten. Allerdings koennten endlose Thinking-Streams Bandbreite verbrauchen (kein Backend-Cap). Siehe BUG-3. |

### Bugs / Verbesserungen

#### BUG-1 (Low, cosmetic, pre-existing): leerer assistant-Placeholder bleibt sichtbar, wenn der erste Event ein `tool_start` ist

**Schritte zur Reproduktion:**
1. User sendet eine Nachricht, die Ollama dazu bringt, SOFORT ein Tool aufzurufen (ohne vorherige Thinking- oder Content-Tokens).
2. `streamingSend` legt einen leeren `assistant`-Platzhalter an (`useChatSessions.ts:312-322`).
3. Erstes SSE-Event ist `tool_start` → `handleToolStart` schliesst `streaming: false` auf dem Platzhalter und schiebt die `tool_call`-Bubble dahinter.
4. Ergebnis: Leerer Assistant-Bubble bleibt oberhalb der Tool-Reihe sichtbar.

Harness Test EDGE-A bestaetigt: nach `tool_start` enthaelt der State eine `assistant: ""`-Message.

**Severitaet:** Low (kosmetisch). Visuelles Artefakt; nichts ist falsch dargestellt.

**Bemerkung:** Vor PROJ-37 trat das ebenfalls auf — der Code in `handleToolStart` (PROJ-35) hat den Platzhalter schon damals so behandelt. PROJ-37 macht das Problem NICHT schlimmer; es kann den Fall sogar abmildern, wenn die meisten Antworten jetzt mit Thinking starten (`appendThinking` konvertiert den Platzhalter in-place).

**Priorisierung:** Wuerde ich nicht fuer PROJ-37-Release blocken. Kandidat fuer eine PROJ-35-Folge-Karte oder fuer den naechsten Touch in PROJ-31/35.

---

#### BUG-2 (Low, cosmetic): leerer `token`-Event-Content schliesst Thinking und oeffnet leeren Assistant-Bubble

**Schritte zur Reproduktion (synthetisch — Backend emittiert es heute nicht):**
1. Backend sendet `{"type":"token","content":""}` direkt nach einem `thinking`-Event.
2. `api.ts:411` prueft `typeof evt.content === "string"`, was fuer `""` zutrifft → `onToken("")` wird gerufen.
3. `appendToken("")` in `useChatSessions.ts:340-356`: last ist `thinking`/streaming → schliesst Thinking, pusht neue `assistant: ""`-Bubble.

Harness Test EDGE-D bestaetigt: leerer streaming-Assistant-Bubble haengt im State.

**Severitaet:** Low. Tritt im normalen Pfad nicht ein, weil `streaming.py:235` `if content:` (truthy) prueft. Aber: defensiver waere `if (typeof evt.content === "string" && evt.content.length > 0)` in `api.ts`.

**Priorisierung:** Nice-to-have. Nicht release-blockierend.

---

#### BUG-3 (Low, hardening): kein Server-seitiges Cap auf Thinking-Volumen

**Schritte zur Reproduktion:**
- Das Modell qwen3:14b kann theoretisch sehr lange Thinking-Bloecke erzeugen (>10k Tokens). Die Spec sagt "EC2: kein Abschneiden auf Backend-Seite". Das ist gewollt. Aber: einzelne, sehr grosse `thinking`-Strings koennen die SSE-Payload-Groesse und die nginx-Buffer belasten.
- Es gibt keinen Mechanismus, das Modell anzuweisen, weniger zu denken (System-Prompt-Anpassungen sind explizit out-of-scope).

**Severitaet:** Low. Bandbreite & UX-Empfinden. Kein Security-Issue.

**Priorisierung:** Beobachten. Nach Deploy Prometheus-Metric fuer Thinking-Tokens nachziehen (steht bereits als optional in der Spec). Folgekarte sinnvoll.

---

#### Anmerkung-1: ENV-Var `OLLAMA_THINK` muss in Live-`.env` ergaenzt werden

Die `.env.example` ist aktualisiert. Der Container nutzt `env_file: .env`. Da der Default im Code `true` ist, funktioniert der Feature-Switch ohne Aenderung der `.env`. Wer Thinking abschalten will (z.B. Voice-Streaming), muss `OLLAMA_THINK=false` in der Server-`.env` setzen und neu starten.

Kein Bug — nur ein Deployment-Hinweis fuer `/deploy`.

---

#### Anmerkung-2: Ollama-API-Vertrag `"think": true` (top-level)

Der Diff verschiebt `think` aus `options` (`"options": {"think": False}`) auf die Top-Ebene des Payloads (`"think": True`). Laut [Ollama-Doku](https://docs.ollama.com/capabilities/thinking) ist `think` ein Top-Level-Feld. Der frueher genutzte `options.think`-Pfad war wahrscheinlich nicht der korrekte (lautlos ignoriert). Aenderung ist konform mit der aktuellen Ollama-API. Achten: Ollama-Version auf dem Server muss `>= 0.5.x` sein (think-Support).

### Regression Testing

| Feature | Status | Befund |
|---|---|---|
| PROJ-30 (alice-chat-stream Backend) | Untouched, modifies only `streaming.py` and `.env.example` | Auth-Flow, `/health`, `/metrics`, JWT-Verifikation, Persistierung unveraendert. Token-Counter weiterhin nur fuer Content. Side-Effect-Struktur (`final_text`, `tool_calls`, `usage`) unveraendert. |
| PROJ-31 (Frontend Streaming-UI) | `useChatSessions.ts` erweitert, nicht ersetzt | Pre-PROJ-37-Pfad (Ollama liefert `thinking: ""`): `appendToken` greift, wie zuvor, fuer alle Tokens. `handleToolStart`/`handleToolEnd` bleiben rueckwaerts-kompatibel (`status` und `summary` sind optional). Harness Test 6 (kein-Thinking-Path) bestaetigt: gleiches Resultat wie vor PROJ-37. |
| PROJ-32 (nginx SSE-Proxy) | Nicht angefasst | SSE-Buffering, Timeouts, Rate-Limits unveraendert. |
| PROJ-34/36 (RS256) | Nicht angefasst | JWT-Verifikation in `auth.py` unveraendert. |
| PROJ-35 (Chat Frontend Redesign) | `ThinkingMessage.tsx` wird erstmals lebendig genutzt | Renderer war vorbereitet, jetzt aktiv. `MessageRole`-Typen unveraendert. `markStreamAborted` ist erweitert (BUG-1 aus PROJ-35 bleibt gefixt: tool_call-Spinner werden weiterhin auf `error` gesetzt). Harness Test 5 bestaetigt. |
| TypeScript Build | `npx tsc --noEmit` clean, keine Fehler | Type-System konsistent (`StreamCallbacks.onThinking` Pflicht — alle Aufrufer aktualisiert) |

### Zusammenfassung

- **Acceptance-Kriterien:** 23 / 23 PASS
- **Edge-Cases:** 7 / 7 PASS
- **Bugs gefunden:** 3 (alle **Low**: 2 pre-existing-/synthetic-Cosmetic, 1 Hardening-Hinweis)
- **Security-Findings:** 0 (keine neuen Risiken; XSS, AuthBypass, Injection, PII-Leak alle clean)
- **Regression:** keine

### Produktionsfreigabe-Empfehlung

**READY** — keine Critical/High-Bugs. Die 3 Low-Items sind kosmetisch bzw. zukuenftiges Hardening; sie blockieren das Release nicht.

Vor dem Deploy bitte sicherstellen, dass:
1. Ollama-Version auf dem GPU-Host `>= 0.5.x` (top-level `think`-Support) ist.
2. Optional: `OLLAMA_THINK=true` explizit in der Server-`.env` setzen (Default ist bereits true).
3. Frontend deployed via `./scripts/deploy-frontend.sh && ./sync-compose.sh`.
4. `alice-chat-stream`-Container neu gebaut wird (`make alice-chat-stream` oder docker-compose build).

**Priorisierung der Low-Bugs (Vorschlag):**
1. BUG-3 (Thinking-Volumen-Cap) — nach Deploy beobachten, ggf. PROJ-38 als Folge-Karte.
2. BUG-1 (leerer Placeholder bei sofortigem `tool_start`) — kann mit PROJ-35-Refactor zusammen, low priority.
3. BUG-2 (leerer Token-Content) — defensive Edit in `api.ts`, 1-Zeiler.

Welche der drei moechtest du fixen lassen, bevor wir `/deploy` machen? Oder reichen alle drei als Folge-Karten?

## Deployment

**Deployed:** 2026-05-13
**Deployed by:** Andreas Steel

### Components Deployed

- **Backend:** `alice-chat-stream` Docker container rebuilt and restarted with updated `streaming.py` and `.env.example`
- **Frontend:** React app rebuilt via `./scripts/deploy-frontend.sh` and deployed to nginx

### Production Notes

- Ollama `think: true` is now active (top-level field, requires Ollama >= 0.5.x)
- `OLLAMA_THINK` env var defaults to `true`; set `OLLAMA_THINK=false` in server `.env` to disable thinking (e.g. for voice use cases)
- Thinking tokens are streamed to the client but NOT persisted in `alice.messages`
- BUG-1, BUG-2, BUG-3 (all Low) deferred as follow-up candidates
