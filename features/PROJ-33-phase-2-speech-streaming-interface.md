# PROJ-33: Phase-2-Vorbereitung — Speech Streaming Interface

**Status:** 🔵 Planned
**Created:** 2026-05-07
**Last Updated:** 2026-05-07

## Kontext & Motivation

Phase 2 sieht ein vollständiges Sprachinterface vor: Whisper STT (Sprache → Text), Piper TTS (Text → Sprache) und Speaker-ID. Die geplante Unterbrechbarkeit der Sprachausgabe (Nutzer spricht ins Mikrofon, während Alice antwortet) erfordert:

1. **Bidirektionale Verbindung**: Nicht nur Server→Client (SSE reicht nicht), sondern auch Client→Server während eines laufenden Streams
2. **Token-Delivery für TTS**: Piper TTS muss Sätze erhalten, sobald sie vollständig sind — nicht erst wenn die gesamte Antwort fertig ist
3. **Interrupt-Signal**: Wenn der Nutzer spricht, muss der laufende Ollama-Stream sofort gestoppt werden
4. **Speaker-ID-Hook**: Der Streaming-Service muss den Nutzer aus dem Audio identifizieren, bevor er den JWT-Auth-Flow startet

Dieses Projekt erweitert `alice-chat-stream` (PROJ-30) um einen WebSocket-Endpunkt und eine Satz-Segmentierungs-Logik für TTS-optimierte Token-Delivery.

## Dependencies

- Requires: PROJ-30 (alice-chat-stream — Basis-Service muss deployed sein)
- Requires: PROJ-31 (Frontend Streaming-UI — SSE-Basis muss funktionieren)
- Enables: Phase-2 Speech Gateway (Whisper STT + Piper TTS + Speaker-ID)
- Parallel zu: Phase-2 Hardware/Container-Setup

## User Stories

- Als Nutzer möchte ich, dass Alice zu sprechen aufhört, wenn ich sie unterbreche, damit wir eine natürliche Konversation führen können.
- Als Nutzer möchte ich, dass die Sprachausgabe beginnt, sobald Alice den ersten vollständigen Satz generiert hat, damit die Latenz gefühlt kürzer ist.
- Als Nutzer möchte ich, dass Alice mich auch ohne Login-Screen erkennt (Speaker-ID), damit der Sprachkanal nahtlos funktioniert.
- Als Entwickler möchte ich, dass Text-Chat (SSE) und Sprach-Chat (WebSocket) denselben Backend-Code teilen, damit Tool-Execution und Memory nur einmal implementiert sind.

## Acceptance Criteria

### WebSocket-Endpunkt
- [ ] `WS /stream/ws` akzeptiert WebSocket-Verbindungen
- [ ] Initial-Handshake: Client sendet `{"type":"auth","token":"<jwt>"}` → Server antwortet `{"type":"auth_ok","user_id":"..."}`
- [ ] Nach Auth: Client sendet `{"type":"message","session_id":"...","content":"<text>"}` → Server streamt Tokens als `{"type":"token","content":"..."}`
- [ ] Interrupt-Signal: Client sendet `{"type":"interrupt"}` → Server bricht laufenden Ollama-Stream sofort ab, sendet `{"type":"interrupted"}`
- [ ] Verbindung bleibt nach Ende einer Antwort offen (eine WS-Verbindung pro Session)

### TTS-optimierte Satz-Segmentierung
- [ ] Token-Stream wird zu Sätzen zusammengesetzt (Trennung an `.`, `!`, `?`, `…`)
- [ ] Vollständige Sätze werden als `{"type":"sentence","content":"Hier ist die Antwort."}` gesendet
- [ ] Satz-Events kommen **zusätzlich** zu Token-Events (beide laufen parallel)
- [ ] Piper TTS-Integration kann `sentence`-Events direkt konsumieren
- [ ] Maximale Satz-Puffer-Länge: 500 Zeichen (lange Sätze werden früher gebrochen)

### Speaker-ID-Hook (Vorbereitung)
- [ ] WebSocket-Handshake akzeptiert alternativ `{"type":"auth_speaker","audio_sample":"<base64-wav>"}` statt JWT
- [ ] Bei Speaker-ID-Auth: Audio-Sample wird an `speaker_id_url` (Umgebungsvariable, noch nicht deployed) weitergeleitet
- [ ] Falls Speaker-ID-Service nicht verfügbar: Fallback auf JWT-Auth-Pflichtfeld
- [ ] Speaker-ID-Result wird als `user_id` in die Session übernommen (gleicher Memory-Code-Path)

### Audio-Input-Streaming (Vorbereitung)
- [ ] WebSocket akzeptiert binäre Nachrichten als Audio-Chunks (WAV/PCM)
- [ ] Audio-Chunks werden in Warteschlange gepuffert und an Whisper-STT-Service weitergeleitet (Umgebungsvariable `WHISPER_URL`, noch nicht deployed)
- [ ] Falls Whisper nicht verfügbar: Binary-Nachrichten werden ignoriert (kein Crash)
- [ ] Whisper-Transkript kommt zurück als `{"type":"transcript","content":"..."}` im WebSocket

### Gemeinsamer Code-Path
- [ ] WebSocket-Handler und SSE-Handler teilen denselben `ChatSession`-Code (Tool-Execution, Memory)
- [ ] Einziger Unterschied: Ausgabe-Transport (WebSocket-Send vs. SSE-Queue)
- [ ] Unit-Tests für `ChatSession` sind transport-agnostisch

### nginx WebSocket-Proxy
- [ ] `/api/ws/` → `alice-chat-stream:8003` mit korrekten WebSocket-Upgrade-Headers
- [ ] `proxy_set_header Upgrade $http_upgrade`
- [ ] `proxy_set_header Connection "upgrade"`
- [ ] `proxy_read_timeout 3600s` (WebSocket-Verbindungen leben Stunden)

## Edge Cases

- Client verliert Netzwerkverbindung → WS-Verbindung wird sauber geschlossen, Session-State bleibt in PostgreSQL
- Interrupt kommt während Tool-Execution → Tool-HTTP-Request wird noch abgewartet (max. 15s), dann Interrupt durchgeführt
- Zwei Interrupt-Signale in Folge → zweites wird ignoriert (kein Crash)
- Audio-Chunk kommt an während LLM noch antwortet → in Puffer, verarbeitet nach `done`-Event
- Speaker-ID identifiziert unbekannten Nutzer → WebSocket sendet `{"type":"auth_error","code":"unknown_speaker"}`, Verbindung bleibt offen für JWT-Auth-Retry
- Piper TTS braucht länger als Sentence-Generation → Sentence-Queue darf auf max. 10 Sätze anwachsen (kein Druck auf LLM)

## Technical Design

### Erweiterte Service-Architektur (PROJ-30 + PROJ-33)

```
alice-chat-stream (FastAPI, Port 8003)
├── POST /stream/chat          ← SSE (PROJ-30)
├── WS   /stream/ws            ← WebSocket (PROJ-33, NEU)
├── GET  /health
└── GET  /metrics

Neue optionale Upstream-Abhängigkeiten (Phase 2, noch nicht deployed):
├── Whisper STT   (WHISPER_URL — Graceful Fallback wenn nicht erreichbar)
├── Piper TTS     (PIPER_URL   — Graceful Fallback wenn nicht erreichbar)
└── Speaker-ID    (SPEAKER_ID_URL — Graceful Fallback wenn nicht erreichbar)
```

### Satz-Segmentierungs-Logik

```python
class SentenceSegmenter:
    """Puffert Tokens und gibt vollständige Sätze aus."""
    SENTENCE_END = re.compile(r'(?<=[.!?…])\s+|(?<=[.!?…])$')
    MAX_BUFFER = 500

    def push(self, token: str) -> list[str]:
        """Gibt fertige Sätze zurück (kann leer sein)."""
        self.buffer += token
        sentences = []
        while match := self.SENTENCE_END.search(self.buffer):
            sentences.append(self.buffer[:match.end()])
            self.buffer = self.buffer[match.end():]
        if len(self.buffer) >= self.MAX_BUFFER:
            sentences.append(self.buffer)
            self.buffer = ""
        return sentences

    def flush(self) -> str | None:
        """Am Stream-Ende: restlichen Puffer ausgeben."""
        result = self.buffer.strip()
        self.buffer = ""
        return result if result else None
```

### WebSocket-Protokoll (vollständig)

**Client → Server:**
```jsonc
{"type":"auth","token":"<jwt>"}                         // Initial-Auth
{"type":"auth_speaker","audio_sample":"<base64-wav>"}   // Alt: Speaker-ID
{"type":"message","session_id":"...","content":"..."}    // Text-Nachricht
{"type":"audio_chunk","data":"<base64-pcm>"}             // Audio-Input
{"type":"interrupt"}                                      // Stopp-Signal
{"type":"ping"}                                           // Keep-Alive
```

**Server → Client:**
```jsonc
{"type":"auth_ok","user_id":"..."}
{"type":"auth_error","code":"invalid_token"}
{"type":"transcript","content":"..."}                    // Whisper-Ergebnis
{"type":"token","content":"..."}                         // LLM-Token
{"type":"sentence","content":"..."}                      // TTS-Satz
{"type":"tool_start","tool":"...","status":"..."}
{"type":"tool_end","tool":"..."}
{"type":"done","usage":{...}}
{"type":"interrupted"}
{"type":"error","message":"..."}
{"type":"pong"}
```

### Umgebungsvariablen (Ergänzung zu PROJ-30)

```env
# Phase-2-Services (optional, Graceful Fallback wenn nicht gesetzt)
WHISPER_URL=http://alice-speech-gateway:8004/transcribe
PIPER_URL=http://alice-speech-gateway:8004/synthesize
SPEAKER_ID_URL=http://alice-speech-gateway:8004/identify
```

### Deliverables

- [ ] `app/websocket.py` — WebSocket-Handler in `alice-chat-stream`
- [ ] `app/segmenter.py` — Satz-Segmentierungs-Logik
- [ ] `app/session.py` — Gemeinsamer `ChatSession`-Code (SSE + WS)
- [ ] nginx WebSocket-Proxy-Block (`/api/ws/`)
- [ ] Graceful-Fallback-Tests für alle drei Phase-2-Services
- [ ] Dokumentation des WebSocket-Protokolls (dieses Dokument)

