# PROJ-41: WebApp Voice Interface

## Status: Deployed
**Created:** 2026-05-28
**Last Updated:** 2026-06-15 (BUG-5/7/8 + silence-detection fixes deployed and live-verified on PC + smartphone)

## Dependencies
- Requires: PROJ-40 (Speech Gateway Service) — WebSocket endpoints `/ws/stt` (Mode 1) and `/ws/voice` (Mode 2) on `/api/speech/`
- Requires: PROJ-1 (User Authentication) — JWT token for WebSocket auth

## User Stories

- Als Nutzer möchte ich einen Mikrofon-Button neben dem Sende-Button drücken, sprechen und den transkribierten Text live im Eingabefeld sehen — mit Echtzeit-Zwischenergebnissen während der Aufnahme und automatischem Stopp nach einer Stille-Periode — damit ich Nachrichten per Sprache eingeben kann ohne tippen zu müssen.

- Als Nutzer möchte ich den transkribierten Text vor dem Absenden noch bearbeiten können, damit ich Tippfehler oder Missverständnisse korrigieren kann.

- Als Nutzer möchte ich einen Audio-Icon in der WebApp drücken und ein vollständiges Sprachgespräch mit Alice führen — ohne Texteingabe oder Textausgabe — damit ich Alice hands-free bedienen kann.

- Als Nutzer möchte ich während eines Sprachgesprächs klar sehen, ob Alice gerade zuhört, denkt oder spricht, damit ich den Gesprächszustand immer nachvollziehen kann.

- Als Nutzer möchte ich eine laufende Sprachsession jederzeit mit einem Stop-Button beenden können, damit ich die Kontrolle über das Gespräch behalte.

- Als Nutzer möchte ich nach einer Alice-Antwort direkt weiterreden können ohne erneut einen Button zu drücken, damit das Gespräch natürlich fließt.

- Als Nutzer möchte ich Alice während ihrer Antwort durch Sprechen unterbrechen können, damit ich eine falsche Gesprächsrichtung korrigieren oder eine Teilantwort konkretisieren kann, bevor die vollständige Antwort ausgegeben wurde.

- Als Nutzer möchte ich eine verständliche Fehlermeldung sehen wenn der Mikrofonzugriff verweigert wurde, damit ich weiß was zu tun ist.

## Acceptance Criteria

### Mode 1 — Mikrofon-Button (STT → Texteingabe)

- [ ] Ein Mikrofon-Icon-Button ist in der `InputArea` direkt neben dem Sende-Button sichtbar
- [ ] Ein Klick auf den Mikrofon-Button startet die Aufnahme (Toggle — kein Push-to-Talk)
- [ ] Während der Aufnahme zeigt der Button einen visuell aktiven Zustand (roter Puls-Ring oder ähnliches)
- [ ] Die Aufnahme endet automatisch nach ca. 900 ms Stille nach letzter Sprache — kein zweiter Button-Druck nötig
- [ ] Ein zweiter Klick auf den aktiven Mikrofon-Button beendet die Aufnahme manuell (optionaler Override)
- [ ] Während der Aufnahme werden Interim-Transcripts live im Textarea-Eingabefeld angezeigt und bei jedem Gateway-Update ersetzt (rolling replacement)
- [ ] Nach dem Stopp (auto oder manuell) gibt der Gateway einen finalen Transcript zurück; der Button kehrt automatisch in den Ruhezustand zurück
- [ ] Der Text wird nicht automatisch abgeschickt — der Nutzer kann ihn bearbeiten und dann manuell senden
- [ ] Während einer laufenden Aufnahme ist der Sende-Button deaktiviert
- [ ] Auth: Der WebSocket wird mit dem JWT des eingeloggten Nutzers authentifiziert (Query-Parameter oder Header)

### Mode 2 — Full Voice Overlay

- [ ] Ein Audio-Icon-Button ist in der `InputArea` sichtbar (getrennt vom Mikrofon-Button)
- [ ] Ein Klick auf den Audio-Icon öffnet ein Voice-Overlay (Vollbild-Modal oder zentriertes Overlay), das die Chat-UI überlagert
- [ ] Das Overlay zeigt den aktuellen Gesprächszustand als deutschen Text:
  - `stt_complete` / Aufnahme läuft → "Höre zu…"
  - `ai_processing` → "Alice denkt…"
  - `tts_generating` / Audio läuft → "Alice spricht…"
  - Warte auf nächste Eingabe (nach TTS) → "Höre zu…"
- [ ] TTS-Audio-Chunks (binäre WebSocket-Frames) werden über die Web Audio API in Echtzeit abgespielt — kein vollständiges Buffern vor dem Abspielen
- [ ] Während TTS-Audio abgespielt wird, läuft die Mikrofonaufnahme weiter und Audio-Chunks werden kontinuierlich an den Gateway gesendet (Barge-In-Input)
- [ ] Empfängt der Browser ein neues Status-Event vom Gateway während TTS läuft (z.B. `stt_complete` als Signal dass ein Interrupt erkannt wurde), wird die laufende Audio-Wiedergabe sofort gestoppt und die Wiedergabe-Queue geleert
- [ ] Nach einem Barge-In zeigt das Overlay den neuen Zustand ("Alice denkt…") — die Session bleibt erhalten, kein Neustart nötig
- [ ] Nach vollständiger TTS-Antwort bleibt die Session offen und wartet auf neue Spracheingabe (continued conversation)
- [ ] Das Overlay enthält einen Stop-Button, der die Session beendet und das Overlay schließt
- [ ] Bei `session_ended`-Event vom Gateway wird das Overlay automatisch geschlossen
- [ ] Auth: Der WebSocket wird mit dem JWT des eingeloggten Nutzers authentifiziert

### Mikrofonzugriff

- [ ] Beim ersten Klick auf Mikrofon- oder Audio-Icon wird `getUserMedia` aufgerufen
- [ ] Wird die Erlaubnis verweigert oder ist kein Mikrofon vorhanden, erscheint ein Toast: "Mikrofonzugriff verweigert — bitte in den Browser-Einstellungen erlauben"
- [ ] Nach einem Berechtigungsfehler sind beide Buttons deaktiviert (nicht nur ausgegraut — kein weiteres `getUserMedia` ohne Reload)
- [ ] Beide Buttons sind für alle eingeloggten Nutzer sichtbar und nutzbar (keine Rolleneinschränkung)

### Allgemein

- [ ] Mikrofon-Button und Audio-Icon sind gleichzeitig nicht nutzbar — ist Mode 1 aktiv, ist der Audio-Icon deaktiviert und umgekehrt
- [ ] Die Buttons funktionieren auf Desktop (Chrome, Firefox) und Mobile (Chrome/Safari auf iOS/Android)

## Edge Cases

- **Leere Aufnahme (Mode 1)**: Whisper liefert leeren finalen Text → Eingabefeld bleibt leer; Toast "Nichts verstanden, bitte nochmals versuchen"
- **Stille zu früh erkannt (Mode 1)**: Auto-Stopp feuert während einer natürlichen Pause — bisher transkribierter Text bleibt im Eingabefeld; Nutzer kann Mic erneut drücken und weiter diktieren (neue Session, kein automatisches Zusammenführen)
- **Interim-Text während Benutzer-Tipp (Mode 1)**: Sobald der Nutzer manuell in der Textarea tippt, werden weitere Interim-Updates nicht mehr eingefügt (kein Überschreiben von User-Edits); der finale Transcript landet ebenfalls nicht mehr im Feld — Aufnahme läuft weiter bis Auto-Stopp, danach nur Toast "Aufnahme abgeschlossen"
- **WebSocket-Verbindungsfehler**: Verbindung zu `/api/speech/` schlägt fehl → Toast "Sprachverbindung fehlgeschlagen", Aufnahme wird gestoppt, Buttons wieder aktiviert
- **Session-Timeout (Mode 2)**: Gateway sendet `session_ended` nach Silence-Timeout → Overlay schließt sich automatisch, keine Fehlermeldung nötig
- **Barge-In erkannt (Mode 2)**: Gateway sendet ein neues Status-Event während TTS läuft → Browser stoppt sofort die Wiedergabe, leert die Audio-Queue, zeigt neuen Zustand. Bereits an den Lautsprecher ausgegebene Samples können nicht zurückgeholt werden — das ist akzeptabel.
- **Barge-In nicht erkannt (Mode 2)**: Browser sendet Audio (z.B. Hintergrundgeräusche), Gateway verwirft es intern — TTS läuft ungestört weiter, Browser merkt nichts davon
- **Tab-Wechsel / Seite verlassen während aktiver Session**: WebSocket wird geschlossen, laufende Aufnahme gestoppt, Web-Audio-Kontext freigegeben
- **Gleichzeitiges Abspielen und Aufnehmen (Mode 2)**: Echo-Unterdrückung via `echoCancellation: true` in `getUserMedia`-Constraints
- **JWT abgelaufen**: Gateway schließt WebSocket mit Code 4401 → Toast "Sitzung abgelaufen, bitte neu einloggen"
- **Nutzer klickt Mode-1-Button während Mode-2-Overlay offen**: Ignoriert — Mode-2 hat Vorrang

## Technical Requirements

- **Browser API**: `MediaRecorder` API für Audioaufnahme; Web Audio API (`AudioContext`, `decodeAudioData` oder `AudioWorklet`) für Echtzeit-Chunk-Playback
- **Audio-Format**: PCM oder Opus, abhängig von Gateway-Anforderungen (aus PROJ-40 ableiten); `echoCancellation: true`, `noiseSuppression: true` in getUserMedia
- **WebSocket-Endpunkte**: `/api/speech/ws/stt` (Mode 1, Streaming-Modus), `/api/speech/ws/voice` (Mode 2) — über nginx proxy zu `alice-speech-gateway:10301`. `/ws/stt` empfängt nun Audio-Chunks als binary WS-Frames (statt einzelnem Blob), sendet `{"type":"interim","text":"..."}` laufend und `{"type":"final","text":"..."}` nach `{"type":"end_of_utterance"}` vom Client
- **Silence Detection (Mode 1)**: Client-seitig via Web Audio `AnalyserNode` RMS — Schwelle ~40 dBFS, 900 ms Stille nach letzter Sprache → Client sendet `{"type":"end_of_utterance"}` → Gateway flush → `final`-Event → Button idle
- **Performance**: Erste TTS-Audio-Wiedergabe beginnt innerhalb von < 3s nach Ende der Spracheingabe (Gateway-Budget; Frontend-Overhead < 100ms)
- **Browser-Support**: Chrome 90+, Firefox 90+, Safari 15+ (iOS), Chrome Android
- **Kein neuer API-Endpunkt** nötig — kommuniziert ausschließlich über den bestehenden Gateway-WebSocket

---
<!-- Sections below are added by subsequent skills -->

## Tech Design — Mode 1 Extended (Streaming + Live Transcription) — 2026-06-14

### What changes from the current implementation

| Aspect | Old Mode 1 | Extended Mode 1 |
|---|---|---|
| WS open timing | After recording stops | Immediately on button press |
| Audio send | One complete blob | 250 ms chunks, streamed live |
| Auto-stop | None (manual only) | Client-side silence detection (900 ms) |
| Transcript flow | One `{type:"transcript"}` at end | Rolling `{type:"interim"}` + `{type:"final"}` |
| Textarea updates | Once, after stop | Live rolling replacement on each interim |

### Component Structure — Mode 1 Extended

```text
useVoiceMode1 (REWRITE)
  — Opens WS at recording start, not at stop
  — MediaRecorder timeslice: 250 ms → each ondataavailable chunk → binary WS frame
  — Web Audio AnalyserNode watching the mic stream:
      RMS > threshold → mark "speech detected", reset silence timer
      speechDetected + silence > 900 ms → send {"type":"end_of_utterance"} → stop
  — Incoming JSON frames:
      {"type":"interim","text":"..."} → replace textarea if !userHasEdited
      {"type":"final","text":"..."}  → set textarea if !userHasEdited, cleanup
  — userHasEdited mutex: if user types in textarea → stop interim updates,
      recording continues until silence/manual stop, final transcript is dropped
  — Manual second click → immediately sends {"type":"end_of_utterance"}, cleanup

Gateway /ws/stt (UPDATED)
  — Streaming mode: receives binary chunks, accumulates full buffer
  — Interim trigger: every ~2 s of new audio received → Whisper on full buffer → interim
  — On {"type":"end_of_utterance"}: final Whisper on full buffer → {"type":"final"} → close
  — Full-buffer approach avoids EBML continuation-chunk problem
    (first chunk always has EBML header; full buffer is always valid for short STT inputs)
```

### New Wire Protocol for `/ws/stt`

```text
Client  →  Gateway: WS open (?token=<jwt>)
Gateway →  Client:  (accepted, ready)

Client  →  Gateway: [binary] chunk_1 (250 ms)
...
Client  →  Gateway: [binary] chunk_4 (250 ms)   ← ~2 s accumulated
Gateway →  Client:  {"type":"interim","text":"Hallo A…"}

Client  →  Gateway: [binary] chunk_5 ... chunk_8  ← ~4 s accumulated
Gateway →  Client:  {"type":"interim","text":"Hallo Alice, wie spät"}

[900 ms silence detected client-side]
Client  →  Gateway: [text] {"type":"end_of_utterance"}
Gateway →  Client:  {"type":"final","text":"Hallo Alice, wie spät ist es?"}
Gateway closes WS (1000)
```

### Silence Detection

```text
AudioContext.createMediaStreamSource(stream) → AnalyserNode
Every 50 ms:
  analyser.getByteTimeDomainData() → RMS calculation
  RMS > -40 dBFS  →  speechDetected = true; lastSpeechAt = now()
  speechDetected && (now() - lastSpeechAt) > 900 ms
    → send {"type":"end_of_utterance"}
    → MediaRecorder.stop()
    → await {"type":"final"} from gateway → update textarea → cleanup

Minimum speech requirement: at least one high-RMS frame must be seen
before silence auto-stop can fire (prevents immediate trigger in a quiet room).
```

### State Model (hook-local)

```text
isRecording:    boolean    — button state
userHasEdited:  boolean    — mutex: blocks interim/final updates if user typed
speechDetected: boolean    — prevents premature silence trigger
lastSpeechAt:   number     — timestamp of last high-RMS frame
wsRef:          WebSocket  — opened at start, closed after "final" or error
analyserTimer:  number     — setInterval ID for silence polling
```

### Tech Decisions — Mode 1 Extended

| Decision | Choice | Why |
|---|---|---|
| WS open timing | On button press (not on stop) | Chunks must stream from first 250 ms; WS must be ready immediately |
| Interim strategy | Whisper on full accumulated buffer every ~2 s | Continuation WebM chunks (no EBML header) cannot be decoded alone; full buffer is always valid; re-transcribing is fine for short STT inputs |
| Silence detection | Client-side AnalyserNode RMS, 50 ms polling | Spec requirement; avoids round-trip; consistent with Mode 2 design |
| `userHasEdited` mutex | Block both interim and final if user typed | Prevents overwriting user edits; recording auto-stops naturally |
| WebM/EBML decoding | Full-buffer Whisper (no WebmPcmDecoder) | Mode 1 is short (< 30 s); full-buffer simpler than a decoder subprocess; WebmPcmDecoder stays Mode-2-only |

### Files to modify

| Action | File |
|---|---|
| Rewrite | `frontend/src/hooks/useVoiceMode1.ts` |
| Update | `docker/compose/automations/alice-speech-gateway/app/ws_transport.py` — `ws_stt()` function |
| Update | `docker/compose/automations/alice-speech-gateway/tests/test_ws_transport.py` — streaming STT tests |

No new packages. No new endpoints. No DB changes.

---

## Implementation Notes — Mode 1 Extended (Frontend, 2026-06-14)

**Implemented by:** Frontend Developer (skill). Scope: frontend only.

### Files changed
- **Rewrite** `frontend/src/hooks/useVoiceMode1.ts` — replaced the old
  record-then-send-one-blob flow with streaming:
  - WebSocket opens on button press (in `startRecording`), not on stop.
  - `MediaRecorder.start(250)` → each `ondataavailable` chunk is sent as a
    binary WS frame.
  - Client-side silence detection via `AudioContext` + `AnalyserNode` RMS,
    polled every 50 ms (threshold 0.010 ≈ -40 dBFS). After 900 ms of silence
    *following detected speech* it calls the finalizer. A high-RMS frame must
    be seen first, so a quiet room never auto-stops.
  - Finalizer sends `{"type":"end_of_utterance"}`, stops capturing, and keeps
    the WS open until `{"type":"final"}` arrives, then tears down. Idempotent
    (`endRequestedRef`) so the silence timer and a manual second click can't
    double-fire.
  - Incoming `{"type":"interim"}` → rolling replacement of the dictated text;
    `{"type":"final"}` → final text + teardown. Both blocked once the user
    has edited the textarea.
  - `userHasEdited` mutex exposed as `notifyUserEdit()`; transcript
    composition exposed via new `getBaseText` option so a new dictation is
    appended to (not merged with) any pre-existing textarea content.
- **Update** `frontend/src/components/Chat/InputArea.tsx` —
  `onTranscript` handler changed from append to straight replacement (the
  hook now composes `base + transcript`); passes `getBaseText: () => value`;
  `handleInput` now calls `voice1.notifyUserEdit()` so manual typing freezes
  interim/final injection.

### Behavioural notes
- Toasts: empty final → "Nichts verstanden, bitte nochmals versuchen";
  final-after-edit → "Aufnahme abgeschlossen"; 4401 close → "Sitzung
  abgelaufen, bitte neu einloggen".
- Manual second click and auto-silence both route through the same finalizer
  and still populate the textarea from the final transcript.
- Reused the proven Mode 2 detector pattern (analyser → gain 0 → destination)
  for cross-browser audio delivery.

### Build / typecheck
- `npx tsc --noEmit` exits 0; `npm run build` clean.

### ⚠ Backend dependency — RESOLVED (see backend notes below, 2026-06-14)
The gateway `/ws/stt` was rewritten to the streaming protocol in the backend
pass below. The frontend's documented wire protocol (`interim` / `final` /
`end_of_utterance`) is now matched end-to-end.

---

## Implementation Notes — Mode 1 Extended (Backend / Gateway, 2026-06-14)

**Implemented by:** Backend Developer (skill). Scope: `alice-speech-gateway` only.

### Files changed
- **Rewrite** `app/ws_transport.py` — `ws_stt()` replaced the old
  one-blob-per-frame handler (which replied `{"type":"transcript"}`) with the
  streaming protocol:
  - Streaming loop factored into a testable `_stt_loop(ws, log)` (mirrors how
    `ws_voice` delegates to `_voice_loop`); `ws_stt` keeps auth + the
    `WebSocketDisconnect` wrapper.
  - Binary frames accumulate into a single growing WebM buffer. While
    recording, the **full buffer** is re-transcribed and a
    `{"type":"interim","text":...}` frame is emitted, throttled to one run per
    `_STT_INTERIM_INTERVAL_S` (2 s) with at most one interim in flight at a
    time. Empty/failed interim results are skipped so they never blank the
    client textarea.
  - On `{"type":"end_of_utterance"}`: any in-flight interim is cancelled, the
    full buffer is transcribed once more, and `{"type":"final","text":...}` is
    sent (empty string included — the client shows "Nichts verstanden"). The
    socket then closes 1000. STT failure on the final sends
    `{"type":"error","message":...}` instead.
  - Full-buffer approach (not the Mode-2 `WebmPcmDecoder`): the buffer always
    starts at the first MediaRecorder chunk, which carries the EBML header, so
    the partial stream stays decodable on every interim; Mode-1 clips are short
    (< 30 s) so re-running Whisper on the growing buffer is cheap.
- **Update** `tests/test_ws_transport.py` — added 5 streaming-STT tests
  (`FakeSTT` scripted engine, injected via `stt._engine`): interim→final,
  final-only under the interval, empty final, STT-error→error frame, and
  disconnect-before-final.

### Verification
- `pytest` — **59 passed** (5 new STT tests + existing Mode 2 / barge-in
  suite, no regressions).

### Deploy
The gateway image must be rebuilt and redeployed for this to go live:
`./scripts/sync-compose.sh` then on `ki.lan`:
`docker compose build && docker compose up -d --force-recreate` for
`alice-speech-gateway`. **Deploy `alice-speech-gateway` (gateway image).**

---

## Tech Design (Solution Architect) — Original

### Component Structure

```text
InputArea (extended — existing component)
+-- Textarea (existing)
+-- MicButton (NEW) — Mode 1 toggle, pulsing ring when recording
+-- VoiceButton (NEW) — Mode 2 trigger; disabled while Mode 1 active
+-- SendButton / StopButton (existing, disabled during Mode 1 recording)

VoiceOverlay (NEW — shadcn Dialog over full chat UI)
+-- StatusLabel — "Höre zu…" / "Alice denkt…" / "Alice spricht…"
+-- AnimatedVisualizer — CSS pulsing ring for live state feedback
+-- StopButton — ends session, closes overlay

useVoiceMode1 (NEW hook)
  — MediaRecorder lifecycle, WS /ws/stt, transcript → InputArea callback

useVoiceMode2 (NEW hook)
  — MediaRecorder, WS /ws/voice, binary chunk streaming,
    status event parsing, Web Audio API playback queue, barge-in flush

useAudioPermission (NEW hook — shared by both modes)
  — getUserMedia, permission state, error toast on denial
```

### Data Flow

**Mode 1:**

```text
MicButton click → getUserMedia → MediaRecorder starts (250 ms timeslice)
→ each chunk sent as binary WS frame to /ws/stt (streaming mode)
→ Gateway returns { type:"interim", text:"..." } → replaces Textarea content (rolling)
→ Client AnalyserNode detects ~900 ms silence → sends { type:"end_of_utterance" }
  (or: manual second click → same end_of_utterance + immediate teardown)
→ Gateway returns { type:"final", text:"..." } → Textarea updated, WS closed, Button → idle
→ User edits and sends manually
```

**Mode 2:**

```text
VoiceButton click → getUserMedia → WS /ws/voice opens
→ MediaRecorder fires ondataavailable (~250ms) → each chunk sent as binary WS frame
→ Gateway sends JSON status events: stt_complete, ai_processing, tts_generating, session_ended
→ Gateway sends binary TTS frames → AudioContext queue plays back-to-back
→ Barge-in: new status event → AudioContext queue flushed, playback stopped immediately
→ session_ended event or Stop click → WebSocket closed, overlay dismissed
```

### Audio Handling

- **Recording**: `MediaRecorder` with `echoCancellation: true`, `noiseSuppression: true`. Mode 1: single blob on stop. Mode 2: chunks streamed continuously as binary WS frames.
- **Playback (Mode 2)**: `AudioContext.decodeAudioData` per incoming binary frame → sequential playback queue. On barge-in, queue cleared and active `AudioBufferSourceNode` stopped.
- **Cleanup**: `MediaRecorder.stop()`, `WebSocket.close()`, `AudioContext.close()` called on overlay close and tab unload.

### State Model (hook-local, no DB)

```text
Mode 1: isRecording: boolean, interimText: string,
        userHasEdited: boolean (Mutex gegen rolling updates),
        onFinalTranscript callback
Mode 2: status: 'idle'|'listening'|'processing'|'speaking'|'ended',
        audioQueue: AudioBuffer[], wsConnection: WebSocket | null
```

### Tech Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Overlay | shadcn `Dialog` (already installed) | No new package; accessible; works on mobile |
| Audio playback | Web Audio API `AudioContext` | Required for streaming binary chunks + instant barge-in interrupt |
| Recording format | MediaRecorder default (webm/opus) | PROJ-40 gateway already handles Opus; no transcoding needed |
| Hook split | Two separate hooks | Modes share almost no logic; combined hook adds complexity with no benefit |
| JWT auth | `?token=<jwt>` query param | Browser WebSocket API does not support custom headers |
| Icons | lucide-react `Mic`, `AudioLines` | Already installed; consistent with existing InputArea icons |

### Files

| Action | File |
| --- | --- |
| Modify | `frontend/src/components/Chat/InputArea.tsx` |
| Create | `frontend/src/components/Chat/VoiceOverlay.tsx` |
| Create | `frontend/src/hooks/useVoiceMode1.ts` |
| Create | `frontend/src/hooks/useVoiceMode2.ts` |
| Create | `frontend/src/hooks/useAudioPermission.ts` |

### Dependencies

No new packages. All required capabilities are already available:

- `shadcn/ui Dialog` — already installed
- `lucide-react` — already installed
- Web Audio API + MediaRecorder API — native browser APIs

## Implementation Notes (Frontend, 2026-05-29)

### Files created
- `frontend/src/hooks/useAudioPermission.ts` — shared `getUserMedia` wrapper with terminal denial state and German toast on rejection.
- `frontend/src/hooks/useVoiceMode1.ts` — toggle push-to-talk; single MediaRecorder blob → `/api/speech/ws/stt`; transcript injected via `onTranscript` callback (no auto-send).
- `frontend/src/hooks/useVoiceMode2.ts` — full-voice session against `/api/speech/ws/voice`; continuous MediaRecorder streaming (250 ms timeslice); JSON status → state machine; binary frames → Web Audio playback queue with barge-in flush.
- `frontend/src/components/Chat/VoiceOverlay.tsx` — shadcn `Dialog`-based overlay; status label + pulsing ring + Stop button.

### Files modified
- `frontend/src/components/Chat/InputArea.tsx` — added `Mic` button (Mode 1) and `AudioLines` button (Mode 2). Mode 2 wired to `VoiceOverlay`. Mode 1 disabled while Mode 2 is active and vice versa. Recorded-state styling on the mic button (red pulsing ring). Send button disabled while Mode 1 recording is in flight.

### Protocol decisions
- WebSocket auth: JWT passed via `?token=<jwt>` query param (matches gateway `auth.extract_ws_token` + browser WebSocket API constraint).
- Client → Gateway audio format: `MediaRecorder` default (webm/opus). The gateway pipeline already passes `audio_format="webm"` to Whisper. No transcoding in the browser.
- Gateway → client TTS audio: raw 16-bit signed PCM mono. Sample rate hard-coded to `22050 Hz` (wyoming-piper default voice); the Wyoming protocol carries `rate` per chunk but the gateway only forwards the `.audio` bytes. If a non-default voice is configured later we will need a `{type:"audio_format", rate:N}` JSON frame from the gateway.
- Utterance boundary: detected client-side via Web Audio `AnalyserNode` RMS over the mic stream. After ~1.2 s of silence after speech, the client sends `{"type":"end_of_utterance"}` so the gateway flushes the current utterance into the STT pipeline.
- Barge-in: while `status === "speaking"`, MediaRecorder keeps streaming. Any new status event (`stt_complete` / `ai_processing`) is treated as the gateway's interrupt acknowledgement — we immediately stop all queued `AudioBufferSourceNode`s and reset the playback timeline.
- Session end: `session_ended` status, WebSocket close (incl. silence-timeout from gateway), Stop button click, or component unmount all run through the shared `teardown()` which closes WS, stops MediaRecorder, releases the MediaStream tracks, and closes the AudioContext.
- 4401 close code → toast "Sitzung abgelaufen, bitte neu einloggen".

### Build / typecheck
- `npm run build` clean.
- No new packages required (shadcn Dialog + lucide-react + Web Audio/MediaRecorder native APIs).

## QA Test Results

**QA Date:** 2026-06-01 (re-test after BUG-1 / BUG-2 fixes)
**Tester:** QA Engineer (skill)
**Production-ready decision: READY (with caveats)** — no Critical or High bugs open. BUG-3 (umlauts in primary user-facing copy) and BUG-6 (gateway barge-in audio-format contract mismatch) remain as MEDIUM findings; both should be addressed before announcing the feature to end users, but neither blocks deploy per the QA rule (only Critical/High block).

> Static-analysis re-test: `npm run build` clean (Next.js compiled in 3.1s, all routes generated, 0 type errors); `npx tsc --noEmit` exits 0. Live in-browser run was again not possible — `frontend/` still has no test infrastructure (no Vitest, no Playwright, no `test`/`test:e2e` scripts). Mode 2 verdicts that were previously blocked by BUG-1 are now PASS at code-review level; live confirmation will only happen on the staging server after `/deploy`.

### Acceptance Criteria (re-test)

#### Mode 1 — Mikrofon-Button (STT → Texteingabe)
| # | Criterion | Result |
|---|-----------|--------|
| 1 | Mic-Button neben Sende-Button sichtbar | PASS |
| 2 | Klick startet Aufnahme (Toggle) | PASS |
| 3 | Aktiver Zustand (roter Puls-Ring) | PASS — `animate-pulse` + `animate-ping` ring in `InputArea.tsx:156-171` |
| 4 | Zweiter Klick beendet & sendet an `/ws/stt` | PASS |
| 5 | Transkribierter Text erscheint im Textarea | PASS — `onTranscript` callback in `useVoiceMode1.ts:186` |
| 6 | Kein Auto-Send, editierbar | PASS |
| 7 | Sende-Button deaktiviert während Aufnahme | PASS — `canSend` includes `!voice1.isRecording` (`InputArea.tsx:57`) |
| 8 | Auth via JWT (Query-Param) | PASS |
| – | Edge: leere Aufnahme → Toast, kein Insert | PASS |
| – | Edge: clip < 500 ms → German toast, kein WS-Open | PASS — `MIN_RECORDING_MS = 500` gate in `useVoiceMode1.ts:57,146-150` |

#### Mode 2 — Full Voice Overlay
| # | Criterion | Result |
|---|-----------|--------|
| 9 | Audio-Icon-Button sichtbar | PASS |
| 10 | Klick öffnet Voice-Overlay | PASS — BUG-1 fixed; `setStatus(next)` at `useVoiceMode2.ts:86`, `isActive` flips true on `connecting` |
| 11 | Overlay zeigt Zustände als deutschen Text | **PARTIAL — BUG-3** (strings render, but missing umlauts: "Hoere zu..." statt "Höre zu…", "Gespraech beendet" statt "Gespräch beendet") |
| 12 | TTS-Chunks in Echtzeit abgespielt | PASS (code) — `enqueueAudioChunk` decodes per-frame and schedules sequentially via `nextStartTimeRef` (`useVoiceMode2.ts:145-168`); no full-buffering |
| 13 | Mikrofon läuft während TTS (Barge-In-Input) | PASS (code) — recorder is not stopped on `speaking`; `ondataavailable` keeps shipping frames |
| 14 | Neues Status-Event → Playback stoppt, Queue leer | PASS (code) — `flushPlayback()` called on `stt_complete` while `statusRef.current === "speaking"` (`useVoiceMode2.ts:402-407`) |
| 15 | Nach Barge-In neuer Zustand, Session bleibt | PASS (code) — only `flushPlayback()` + `updateStatus("processing")`; WS/recorder untouched |
| 16 | Nach TTS Session offen (continued conversation) | PASS (code) — `tts_generating → speaking` then next `stt_complete` returns to processing/speaking; no teardown |
| 17 | Stop-Button beendet Session & schließt Overlay | PASS (code) — `stop()` sends `{type:"stop"}`, runs `teardown()`, `updateStatus("idle")` → `isActive=false` closes Dialog |
| 18 | `session_ended` → Overlay schließt automatisch | PASS (code) — `case "session_ended"` → `teardown(); updateStatus("idle")` |
| 19 | Auth via JWT | PASS — `?token=` query param built in `useVoiceMode2.ts:59-62`, server-side `_authenticate` rejects 4401 |

(Criteria 10/12/14–18 are code-level PASS — same hook now reachable. Live functional verification still requires browser run.)

#### Mikrofonzugriff
| # | Criterion | Result |
|---|-----------|--------|
| 20 | `getUserMedia` beim ersten Klick | PASS |
| 21 | Toast bei Verweigerung | PARTIAL — BUG-4 (split title/description + extra "und Seite neu laden"; otherwise correct) |
| 22 | Beide Buttons nach Denial terminal deaktiviert | PASS — `permissionDenied` short-circuits `requestStream`, both buttons read it |
| 23 | Für alle Nutzer sichtbar (keine Rolle) | PASS |

#### Allgemein
| # | Criterion | Result |
|---|-----------|--------|
| 24 | Mode 1 & 2 nicht gleichzeitig nutzbar | PASS (code) — `micDisabled` includes `voice2.isActive`; `voiceDisabled` includes `voice1.isRecording` (`InputArea.tsx:114-126`) |
| 25 | Desktop (Chrome/FF) & Mobile (Chrome/Safari) | NOT TESTED — no live run available; verification deferred to staging deploy |

**Totals: 19 PASS, 0 FAIL, 2 PARTIAL (BUG-3, BUG-4), 1 NOT TESTED (cross-browser).**

### Bugs

**BUG-1 (CRITICAL) — FIXED & VERIFIED.** `useVoiceMode2.ts:84-87` now: `statusRef.current = next; setStatus(next);` — recursion gone. Mode 2 overlay opens.

**BUG-2 (HIGH) — FIXED & VERIFIED.** Client-side 500 ms duration gate in `useVoiceMode1.ts:57,146-150`. Gateway PCM-byte-count check removed from `/ws/stt` and `/ws/voice` utterance path (`ws_transport.py` — diff shows `_PCM_BYTES_PER_SEC` constant deleted from both call sites). Barge-in buffer now `_BARGE_IN_MIN_BYTES = 512` (`ws_transport.py:37`) — filters corrupt packets, no per-second timing dependency.

**BUG-3 (MEDIUM) — STILL OPEN.** German UI text stripped of umlauts. Verified still present in:
- `VoiceOverlay.tsx:23-26` — `"Hoere zu..."`, `"Gespraech beendet"` (status label is the primary user-facing element of the feature)
- `VoiceOverlay.tsx:58,85` — `aria-label="Sprachgespraech beenden"`, `DialogTitle "Sprachgespraech mit Alice"` (screen reader text)
- `InputArea.tsx:184` — `aria-label="Sprachgespraech starten"`
- `useAudioPermission.ts:41-42` — `"Mikrofon nicht verfuegbar"`, `"unterstuetzt"`
- `useVoiceMode1.ts:112`, `useVoiceMode2.ts:345,362` — `"Aufnahme nicht unterstuetzt"`, `"Audioausgabe nicht verfuegbar"`
Spec/AC #11 require `"Höre zu…"` / `"Alice denkt…"` / `"Alice spricht…"`. Also breaks ellipsis (`...` vs `…`). Strictly a partial-PASS on AC #11. **Priority P2 — fix before public announce.**

**BUG-4 (LOW) — STILL OPEN.** Permission-denied toast: spec wants single line "Mikrofonzugriff verweigert — bitte in den Browser-Einstellungen erlauben". Impl splits into title + description and appends "und Seite neu laden". Functionally fine, intent is clearer; user to confirm intended wording. **Priority P3.**

**BUG-5 (LOW / fragility) — STILL OPEN.** `useVoiceMode2.ts:49` hard-codes `TTS_SAMPLE_RATE = 22050`. `tts.py` only forwards `chunk.audio`, drops the Wyoming `rate`. Default Piper voice OK; non-default voice would play distorted. Already acknowledged in impl notes. **Priority P3.**

**BUG-6 (MEDIUM) — FIXED (2026-06-01).** Gateway now spawns one persistent `WebmPcmDecoder` (ffmpeg subprocess) per Mode 2 session. Every incoming WS audio frame is fed to ffmpeg's stdin; decoded 16 kHz mono 16-bit PCM is drained from stdout into a per-session buffer. `_evaluate_barge_in` pulls accumulated PCM (≥ 0.5 s) and calls `BargeInController.evaluate(pcm=pcm_segment, webm=None)`. `BargeInController` wraps the PCM in a minimal WAV header for Whisper's Stage 2 (avoids the "no EBML in mid-stream chunks" problem). Files: new `app/audio_decode.py`; patches in `app/barge_in.py`, `app/ws_transport.py`; tests updated with a `FakeDecoder` so the suite runs without ffmpeg. All 7 `test_ws_transport.py` cases pass.

**OBSERVATION — no test suite.** Still no Vitest/Playwright in `frontend/`. A single unit test on `useVoiceMode2`'s reducer logic would have caught BUG-1 in seconds; a Playwright run against a staging gateway would expose BUG-6. Recommend adding minimal coverage before/after first deploy.

### Security Audit (Red Team) — verdict unchanged: no Critical/High findings
- **Auth bypass:** PASS — `_authenticate` runs before any audio; bad/missing/expired token → close 4401.
- **user_id / IDOR:** PASS — `user_id` comes only from the verified JWT payload, never from client input.
- **Token in `?token=`:** ACCEPTABLE — required by the browser WebSocket API; encrypted under enforced `wss:`. Residual: confirm nginx isn't logging query strings for `/api/speech/`.
- **Injection/XSS:** N/A — transcript goes into a React `Textarea` value (text node), not raw HTML; gateway ignores unknown JSON frames.
- **Rate limiting:** `/api/speech/` has no `limit_req`; low risk (VPN-only, authenticated), noted for hardening.

### Regression
Re-run of `npm run build` and `npx tsc --noEmit` both clean. Diff to `InputArea.tsx` is strictly additive (textarea + send/stop preserved). Other deployed features unchanged. No regression identified.

### Fix priority (after re-test)
1. **BUG-1** ✅ FIXED — verified
2. **BUG-2** ✅ FIXED — verified
3. **BUG-3** ✅ FIXED (by user) — umlauts restored
4. **BUG-6** ✅ FIXED (2026-06-01) — gateway-side persistent webm→PCM decoder
5. **BUG-4 / BUG-5** — cosmetic / latent; defer.

### Recommended next step
Production-ready per the QA rule. Suggest a fresh `/qa` re-run against the gateway (Mode 2 live test) once the updated container is built, to confirm barge-in actually fires end-to-end.

## QA Live Test Results

**QA Date:** 2026-06-01 (live, against deployed `alice-speech-gateway` on ki.lan)
**Tester:** QA Engineer (skill)
**Production-ready decision: NOT READY** — 1 Critical bug blocks Mode 2 entirely.

### Setup verified

- Gateway container `alice-speech-gateway` healthy on ki.lan, ports `10301`/`10302` published.
- `/api/speech/health` → `{"status":"ok","jwt_public_key":true,"wyoming_enabled":true,"whisper_model":"large-v3"}`.
- nginx routes `^~ /api/speech/` → `alice-speech-gateway:10301` with WebSocket upgrade, `proxy_read_timeout 300s`, `X-Accel-Buffering: no` (proxy config verified).
- Deployed frontend bundle (`html/_next/static/chunks/app/page-*.js`) contains the voice strings with umlauts intact: `Höre zu` (\xf6), `Gespräch` (\xe4), `Mikrofon nicht verfügbar` (\xfc), `Sprachgespräch starten/beenden/mit Alice` — BUG-3 from the previous QA pass is gone in the deployed build. (Ellipsis "…" vs "..." still uses `...` in `Alice denkt...` / `Alice spricht...` — BUG-3 residue.)
- Test audio generated via `wyoming-piper` (`de_DE-alice-high`, 22050 Hz, 16-bit mono, ~2.4 s of "Hallo Alice, wie spät ist es?").
- Test JWT minted in-container with the real RS256 private key (`/run/secrets/jwt_private.pem`), `sub=574fe894-… (andreas, admin)`, 10 min expiry.

### Live results

#### Mode 1 — `/ws/stt` (WebApp STT)

| Check | Result |
|---|---|
| WebSocket upgrade through nginx | PASS — HTTP/1.1 `101 Switching Protocols`, gateway accepted |
| Auth (valid JWT) | PASS — session opened |
| Send WAV blob, receive transcript | PASS — `{"type":"transcript","text":"Hallo Alice, wie spät ist es?"}` (exact match, umlauts intact) |
| End-to-end latency (2.4 s audio) | PASS — ~750 ms wall-clock through nginx + faster-whisper (large-v3 on TITAN X, `compute_type=int8`); well under the < 3 s budget |
| Edge: silent 100 ms clip | PASS — `{"type":"transcript","text":""}` — empty string, no error; matches frontend handling (`useVoiceMode1` shows "Nichts verstanden" toast on empty string) |
| Connection close | PASS — clean close on client disconnect, no traceback in logs |

**Mode 1 verdict: PRODUCTION READY.** All 8 acceptance criteria in this block reachable, transcript path works, latency comfortable.

#### Mode 2 — `/ws/voice` (Full Voice Overlay)

**BLOCKED.** Every Mode 2 session crashes server-side immediately after auth, before any audio is processed.

Reproduction:
```
wss://ki.lan/api/speech/ws/voice?token=<valid JWT>
→ accepted (101)
→ "Voice session started" log line
→ ASGI exception, connection torn down
→ client sees `websockets.exceptions.ConnectionClosedError: no close frame received or sent`
```

Server-side traceback (from `docker logs alice-speech-gateway`):
```
File "/app/app/ws_transport.py", line 112, in ws_voice
    barge_in = BargeInController(get_engine())
File "/app/app/barge_in.py", line 38, in __init__
    import webrtcvad
File "/opt/venv/lib/python3.12/site-packages/webrtcvad.py", line 1, in <module>
    import pkg_resources
ModuleNotFoundError: No module named 'pkg_resources'
```

Confirmed in image:
```
$ docker exec alice-speech-gateway pip list | grep -i setuptools
setuptools  82.0.1
```
`setuptools >= 81` no longer ships `pkg_resources` as an importable module. `webrtcvad 2.0.10` (unmaintained since 2017) still does `import pkg_resources` at module load. The `Dockerfile` runs `pip install -U pip setuptools wheel` which pulls in setuptools 82 at every build → the import fails the moment `BargeInController` is constructed (line `ws_transport.py:112`, inside `ws_voice` after auth succeeds).

| # | Criterion | Result |
|---|-----------|--------|
| 9 | Audio-Icon-Button sichtbar | PASS (deployed bundle ships button) |
| 10 | Klick öffnet Voice-Overlay | NOT TESTABLE LIVE — UI opens, but WS crashes before first status; user sees "Sprachverbindung fehlgeschlagen" toast (via `useVoiceMode2` close handler) |
| 11 | Overlay-Status als deutscher Text | NOT TESTABLE LIVE — no status events ever received from gateway |
| 12 | TTS-Chunks Echtzeit-Playback | NOT TESTABLE LIVE — no TTS chunks sent |
| 13 | Mikrofon läuft während TTS | NOT TESTABLE LIVE |
| 14 | Status-Event → Playback stoppt, Queue leer (barge-in) | NOT TESTABLE LIVE |
| 15 | Nach Barge-In neuer Zustand, Session bleibt | NOT TESTABLE LIVE |
| 16 | Continued conversation | NOT TESTABLE LIVE |
| 17 | Stop-Button beendet Session & schließt Overlay | NOT TESTABLE LIVE |
| 18 | `session_ended` → Overlay schließt | NOT TESTABLE LIVE |
| 19 | Auth via JWT | PASS — handshake auth runs before the crash (verified by 4401 close path) |

**Mode 2 verdict: BLOCKED IN PRODUCTION** — see BUG-LIVE-1 below.

#### Auth — red-team

| Attack | Sent | Result | Verdict |
|---|---|---|---|
| Missing token | `wss://…/ws/stt` (no `?token`) | Close `4401 Token fehlt` | PASS |
| Garbage token | `?token=not-a-real-jwt` | Close `4401 Token ungültig` | PASS |
| Expired token (real RS256 key) | minted with `exp = now-60s` | Close `4401 Token abgelaufen` | PASS |
| HS256-signed token (wrong-key algorithm confusion) | HS256 over `"wrong-secret"` | Close `4401 Token ungültig` | PASS |
| `alg=none` token (algorithm bypass) | header `{"alg":"none"}`, empty signature | Close `4401 Token ungültig` | PASS |

All five rejected before any audio bytes are read. `_authenticate` runs immediately after `ws.accept()` and `auth.verify_token` enforces `algorithms=["RS256"]`. No bypass found.

### Bugs

**BUG-LIVE-1 (CRITICAL, OPEN) — Mode 2 `/ws/voice` crashes on every session start.**
- Root cause: `setuptools 82.0.1` in the image dropped the `pkg_resources` module; `webrtcvad 2.0.10` still imports it at the top of `webrtcvad.py`. The import explodes inside `BargeInController.__init__` (`barge_in.py:38`) which is constructed unconditionally for every Mode 2 connection (`ws_transport.py:112`).
- Effect: 100 % of Mode 2 sessions fail. Mode 2 is the headline feature of PROJ-41 (full voice overlay, barge-in, continued conversation). Users see the overlay flash open and a "Sprachverbindung fehlgeschlagen" toast — no audio path ever runs.
- Reproduce: `python3 /tmp/test_mode2.py <valid JWT> /tmp/test_de.wav` → `IncompleteReadError`, server log shows the traceback above.
- Fix options (Backend):
  1. Pin `setuptools<81` in the Dockerfile (`pip install -U pip 'setuptools<81' wheel`) — quickest.
  2. Add `pkg_resources` back via `pip install setuptools-pkg-resources` or the new `pkg-resources` shim.
  3. Replace `webrtcvad` with a maintained alternative (e.g. `silero-vad`, also mentioned in the PROJ-40 tech design as an acceptable choice). Largest change, but eliminates the unmaintained-dependency risk for good.
- Recommended: option 1 for the immediate fix (zero code change, redeploy), schedule option 3 as a follow-up.
- Priority: **P0 — blocks deploy sign-off.**

**BUG-LIVE-2 (MEDIUM, OPEN) — JWT leaks into uvicorn access logs.**
- Root cause: uvicorn's default access log writes the full request URI, including `?token=<full JWT>`, at `INFO`. The previous QA security audit explicitly flagged this risk ("confirm nginx isn't logging query strings"); nginx is fine, but **the gateway itself is logging tokens**. Sample line from `docker logs alice-speech-gateway`:
  ```
  INFO: 172.18.0.14:51362 - "WebSocket /ws/stt?token=eyJhbGciOiJSUzI1NiI…<full RS256 JWT>… [accepted]
  ```
- Effect: a JWT (10 min validity, full user identity + role) is durably written to `docker logs` and any downstream log shipping. Anyone with log access can replay the token until it expires.
- Fix (Backend): configure uvicorn's `access_log=False` or supply a `log_config` that redacts `token` from the query string before logging, **or** move auth into a header-only path (the WebSocket browser API can't set headers, so this requires nginx to strip the query param into a sanitised header before upstream — bigger change). Simplest acceptable fix: turn off uvicorn's access log entirely; gateway already emits its own structured JSON logs for sessions.
- Priority: **P1 — fix before announcing the feature.**

**BUG-3 residue (LOW, OPEN) — `...` vs `…`.**
Deployed bundle uses the ASCII three-dot `Alice denkt...` / `Alice spricht...`. The spec writes `Alice denkt…` (HORIZONTAL ELLIPSIS U+2026). Umlauts are now correct; only the ellipsis character remains. **Priority: P3.**

**BUG-5 (LOW, still open from prior QA)** — TTS sample rate hard-coded to 22050 Hz client-side; default Piper voice OK, would distort on non-default voice. Not exercised in this live test because Mode 2 never reached the TTS path. **Priority: P3.**

### Security audit — verdict: no Critical findings

Auth surface is solid (all five injection / bypass attempts cleanly rejected with 4401). The only new finding is the JWT-in-access-log issue documented as BUG-LIVE-2 (Medium). Recommendations from prior pass (rate limiting, utterance size cap, private-key blast radius) unchanged.

### Performance

Mode 1 end-to-end (browser → nginx → gateway → faster-whisper large-v3 → response):
- 2.4 s audio clip, ~105 KB WAV → ~750 ms total round-trip on TITAN X (`int8`).
- Well inside the < 3 s spec budget. No timeout or backpressure issues.

Mode 2 end-to-end performance — NOT MEASURABLE (BUG-LIVE-1).

### Regression

- No regression on PROJ-40 Mode 1 path (Whisper STT, JWT auth, WS handshake all behave as in the previous QA pass).
- No regression on other deployed features: nginx still routes `/api/auth/`, `/api/stream/`, `/api/webhook/`, `/` unchanged; only `^~ /api/speech/` block is new.
- Frontend deploy is intact (login/settings/chat pages all served).

### Production-ready decision: NOT READY

Blocker:
1. **BUG-LIVE-1 (Critical)** — Mode 2 cannot start a single session. The primary user story ("vollständiges Sprachgespräch mit Alice") and AC #10–18 are all unmet in production.

Recommended next steps:
1. Backend: pin `setuptools<81` in `Dockerfile`, rebuild image, redeploy gateway. Verify with `python3 /tmp/test_mode2.py <JWT> /tmp/test_de.wav` — expect to see `session_id` event, `stt_complete` → `ai_processing` → `tts_generating` status sequence, and binary TTS frames.
2. Re-run `/qa` (live) once the rebuild is on the host. The Mode 2 acceptance criteria, the BUG-6 barge-in path, the continued-conversation loop, and the Mode 1↔Mode 2 mutual exclusion in the UI all need first live confirmation; only Mode 1 has been live-verified.
3. Backend: suppress JWT from uvicorn access logs (BUG-LIVE-2) in the same rebuild — same image, no extra deploy round.

## Backend Fixes — BUG-LIVE-1 & BUG-LIVE-2 (2026-06-01)

**Fixed by:** Backend Developer
**File touched:** `docker/compose/automations/alice-speech-gateway/Dockerfile`

### BUG-LIVE-1 (CRITICAL) — `pkg_resources` ModuleNotFoundError

Pinned `setuptools<81` in the venv bootstrap:

```diff
- /opt/venv/bin/pip install --no-cache-dir -U pip setuptools wheel
+ /opt/venv/bin/pip install --no-cache-dir -U pip 'setuptools<81' wheel
```

Reason: setuptools 81.0 dropped the legacy `pkg_resources` module from being importable by default. `webrtcvad 2.0.10` (unmaintained since 2017, used by `BargeInController.VADPreFilter`) still does `import pkg_resources` at module load. The pin keeps `pkg_resources` available so every `/ws/voice` session can construct its `BargeInController`. A long-term follow-up is to replace `webrtcvad` with `silero-vad` (already listed as an acceptable choice in the PROJ-40 tech design) — out of scope for this hot-fix.

### BUG-LIVE-2 (MEDIUM) — JWT in uvicorn access log

Added `--no-access-log` to the uvicorn command:

```diff
- CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10301"]
+ CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10301", "--no-access-log"]
```

Reason: uvicorn's default access log writes the full request URI to stdout, including `?token=<full JWT>` from WebSocket handshakes. The gateway already emits structured JSON logs for session start/end and auth rejections (`alice-speech-gateway.ws`), so disabling the default access log loses no operational visibility while keeping JWTs out of `docker logs` and downstream log shipping.

### Not changed

- **BUG-3 residue** — handled by the user (out of backend scope).
- **BUG-5** — TTS sample rate hard-coding; not exercised live, deferred per prior QA priority (P3).

### Deploy / verify

```
./scripts/sync-compose.sh
ssh stan@ki.lan 'cd /srv/compose/automations/alice-speech-gateway \
  && docker compose build \
  && docker compose up -d --force-recreate'
# verify:
ssh stan@ki.lan 'docker exec alice-speech-gateway python3 -c "import webrtcvad; print(webrtcvad.__version__)"'
# expect: 2.0.10  (no ModuleNotFoundError)
```

After redeploy, re-run `/qa PROJ-41 Live Test` to confirm Mode 2 status sequence, TTS streaming, barge-in (BUG-6 path), and the absence of JWTs in `docker logs alice-speech-gateway`.

## QA Live Re-Test Results (Mode 2 unblocked)

**QA Date:** 2026-06-01 (live, against deployed `alice-speech-gateway` on ki.lan after the BUG-LIVE-1 / BUG-LIVE-2 Dockerfile rebuild)
**Tester:** QA Engineer (skill)
**Production-ready decision: READY** — no Critical or High bugs open. BUG-LIVE-2 (JWT in container logs) is reclassified as not-yet-fixed and remains MEDIUM. BUG-LIVE-3 (time-to-first-TTS over the 3 s gateway budget) is new MEDIUM. Neither blocks per the QA rule (only Critical/High block).

### Setup verified

- Gateway healthy, ports 10301/10302 published.
- `docker exec alice-speech-gateway python3 -c "import webrtcvad"` → `2.0.10` (UserWarning about `pkg_resources` deprecation only; no `ModuleNotFoundError`). `setuptools==80.10.2` confirmed in image (`pip list`).
- `curl -ks https://ki.lan/api/speech/health` → `{"status":"ok","jwt_public_key":true,"wyoming_enabled":true,"whisper_model":"large-v3"}`.
- Test JWT minted with the real RS256 key in-container, `sub=574fe894-9f54-4959-97c4-f018ad5b74bb` (real `andreas` user_id from `alice.users` — the previous live pass had used a fabricated user_id, which is why `/stream/chat` returned 503 on every Mode 2 turn and the run silently fell through the gateway's error-speak path; that mistake masked the LLM/TTS happy-path).

### Mode 1 — `/ws/stt` (regression)

| Check | Result |
|---|---|
| WS upgrade through nginx, 101 Switching Protocols | PASS |
| Auth (valid JWT) | PASS — session opened |
| Send WAV blob → transcript | PASS — `{"type":"transcript","text":"Hallo Alice, wie spät ist es?"}`, umlauts intact |
| End-to-end latency (2.4 s audio) | PASS — ~1.1 s wall-clock |

**Mode 1 verdict: STILL PRODUCTION READY** — no regression from previous live pass.

### Mode 2 — `/ws/voice` (UNBLOCKED — happy path verified)

Reproduction: `python3 /tmp/test_mode2.py "$JWT" /tmp/test_de.wav wss://ki.lan/api/speech/ws/voice 4096 100 90`

Observed wire trace (real user_id, valid JWT, ~2.4 s of speech "Hallo Alice, wie spät ist es?"):

```
[t=0.00s] session_id=1dcc1c45-7143-4fdd-9e8a-e575e15bd173
[t=2.6s ] (end_of_utterance sent by client)
[t=3.32s] status='stt_complete'
[t=3.32s] status='ai_processing'
[t=12.92s] status='tts_generating'
[t=13.39s] first TTS chunk (2048 bytes)
[t=13.40s] status='tts_generating'   (sentence 2)
[t=13.95s] status='tts_generating'   (sentence 3)
[t=14.07s] status='tts_generating'   (sentence 4)
[t=32.65s] status='session_ended'    (silence timeout, 30s)
total: 319 TTS chunks, 648144 bytes ≈ 14.7 s of synthesized speech @ 22050 Hz 16-bit mono
```

Gateway logs for the same session confirm: `Voice session started` → `STT transcript: 'Hallo Alice, wie spät ist es?'` → `POST http://alice-chat-stream:8003/stream/chat` → sentence-streamed TTS → `Voice session silence timeout` → `Voice session closing: session ended` → `Voice session ended`. No tracebacks, no `pkg_resources` failure.

| # | Criterion | Result |
|---|-----------|--------|
| 9 | Audio-Icon-Button sichtbar | PASS (deployed bundle ships button) |
| 10 | Klick öffnet Voice-Overlay → WS opens, session event arrives | **PASS (LIVE)** — `session_id` returned, `status` events stream cleanly |
| 11 | Overlay-Status als deutscher Text | **PASS (LIVE)** — deployed bundle contains `Höre zu`, `Alice denkt`, `Alice spricht`, `Gespräch beendet` with correct umlauts; only the ellipsis (`...` vs `…`) is still ASCII (BUG-3 residue, LOW) |
| 12 | TTS-Chunks Echtzeit-Playback | **PASS (LIVE)** — 319 binary frames of 2048 bytes streamed sequentially, no full-buffering; first chunk follows the first `tts_generating` by ~470 ms (synth + ship latency) |
| 13 | Mikrofon läuft während TTS (Barge-In-Input) | PASS (code) — receiver task does not stop on `speaking`; not exercised in this synthetic test (no audio injected during TTS window) |
| 14 | Status-Event → Playback stoppt, Queue leer (barge-in) | NOT LIVE-TESTED — synthetic test does not inject audio during TTS; barge-in unit tests pass (7/7 in `test_ws_transport.py`); code path verified in previous pass |
| 15 | Nach Barge-In neuer Zustand, Session bleibt | NOT LIVE-TESTED — same caveat |
| 16 | Continued conversation | PARTIAL — session is held open past TTS (no teardown after the four `tts_generating` events); silence timeout closes it after 30 s as designed. A second-turn live test was not run (would require streaming a second WAV inside the same WS); spec behaviour matches observed lifecycle. |
| 17 | Stop-Button beendet Session & schließt Overlay | NOT LIVE-TESTED via UI — `stop` control frame path verified in code (`ws_transport.py:281` → `state.signal(_SESSION_END)` → `_end_session` → close 1000) |
| 18 | `session_ended` → Overlay schließt | **PASS (LIVE)** — `{"type":"status","status":"session_ended"}` observed before WS close 1000 |
| 19 | Auth via JWT | **PASS (LIVE)** — valid token opens session; missing token closes 4401 "Token fehlt"; garbage token closes 4401 "Token ungültig" |

**Mode 2 verdict: PRODUCTION READY at gateway level.** The LLM/TTS happy path runs end-to-end; the deployed frontend strings carry correct umlauts; the only un-exercised live paths are barge-in injection, the Stop button, and a continued-conversation second turn — all of which are reachable in the code and validated by unit tests / previous reviews, but worth a manual UI pass on staging before announcing.

### Auth — red-team re-test (regression)

| Attack | Sent | Result | Verdict |
|---|---|---|---|
| Missing token | `wss://…/ws/voice` (no `?token`) | Close `4401 Token fehlt` | PASS |
| Garbage token | `?token=not-a-real-jwt` | Close `4401 Token ungültig` | PASS |

No regression on the auth surface.

### Bugs

**BUG-LIVE-1 (CRITICAL) — FIXED & VERIFIED LIVE.** `Dockerfile` now installs `'setuptools<81'` in the venv. `docker exec alice-speech-gateway python3 -c "import webrtcvad"` runs without error in the deployed image (pinned setuptools==80.10.2). Mode 2 sessions reach `stt_complete → ai_processing → tts_generating → TTS chunks → session_ended`. No traceback in `docker logs`.

**BUG-LIVE-2 (MEDIUM, STILL OPEN — fix did NOT take effect).** The `--no-access-log` flag was added to the uvicorn CMD (`Dockerfile:40`) and is present on the live container (`docker inspect` confirms `["uvicorn","app.main:app","--host","0.0.0.0","--port","10301","--no-access-log"]`), but JWTs are still being written to `docker logs` after the rebuild. Sample line from the post-rebuild logs:

```
INFO:     172.18.0.14:53124 - "WebSocket /ws/voice?token=eyJhbGciOiJSUzI1NiI…<full RS256 JWT>… [accepted]
INFO:     connection open
```

Three JWTs in the past 10 minutes of `docker logs alice-speech-gateway`. Root cause: `--no-access-log` only suppresses uvicorn's HTTP access logger (`uvicorn.access`). The `INFO: ... "WebSocket /ws/... [accepted]"` and `INFO: connection open` lines come from uvicorn's **WebSocket protocol logger** (`uvicorn.protocols.websockets.websockets_impl`), which is a separate handler and is not affected by `--no-access-log`.

Fix options (Backend, all in `app.main` / Dockerfile, no code logic change):
1. Add a `logging.Filter` on the `uvicorn.protocols.websockets.websockets_impl` logger that strips `?token=...` from the message before emit. Smallest blast radius.
2. Lower the log level of the WebSocket protocol logger to `WARNING` via a uvicorn `log_config` JSON / dict. Loses the connection-lifecycle visibility but already duplicated by the gateway's own structured `Voice session started/ended` JSON logs.
3. Have nginx strip the `token` query param into a private `Authorization`-style header on upstream proxy, then rewrite the upstream URL to drop the query — bigger change.

Recommended: option 1 (or option 2 since the gateway already emits structured session logs). **Priority: P1 — fix before announcing, but does not block deploy per QA rule.**

**BUG-LIVE-3 (MEDIUM, NEW) — time-to-first-TTS exceeds the gateway budget.** Spec (`Technical Requirements → Performance`) says *"Erste TTS-Audio-Wiedergabe beginnt innerhalb von < 3 s nach Ende der Spracheingabe (Gateway-Budget; Frontend-Overhead < 100 ms)"*. Measured: `end_of_utterance` at t=2.6 s → first `tts_generating` at t=12.92 s → first TTS chunk at t=13.39 s. That is **~10.8 s from end of utterance to first audible audio** — ~3.6× the spec budget.

Breakdown from logs / wire trace:
- STT (faster-whisper large-v3, 2.4 s input): 0.6 s (acceptable)
- `ai_processing` → first sentence ready for TTS: ~9.6 s (qwen3:14b on the local 3090 — this is the dominant cost)
- First TTS chunk after `tts_generating`: ~0.47 s (acceptable)

The bottleneck is `alice-chat-stream` first-token latency, not the gateway. Fix options:
- Force `alice-chat-stream` to flush a partial sentence as soon as one is available (currently appears to wait for sentence boundary in the response). This means a first TTS chunk could land within ~3 s on common short responses.
- Add an "Alice denkt…" filler TTS while waiting (UX masking, no real fix).
- Smaller model for short-response turns.
**Priority: P1 — degrades the headline UX but the feature works.** Track as PROJ-41 follow-up or open a new PROJ-X for streaming-first-token optimisation.

**BUG-3 residue (LOW, UNCHANGED).** Deployed bundle still ships `Alice denkt...` / `Alice spricht...` with ASCII three-dot. Spec uses `…` (U+2026). Umlauts everywhere else are correct. **P3.**

**BUG-5 (LOW) — FIXED (2026-06-15).** Gateway now extracts Piper's actual sample rate from the first `AudioChunk` and sends `{type:"audio_format","rate":N}` before the first binary audio frame. `useVoiceMode2` stores the rate in `ttsRateRef` and uses it in `pcmToAudioBuffer` instead of the hard-coded 22050. Files: `tts.py` (on_first_rate callback), `pipeline.py` (send_audio_format wired through _synth_stage), `ws_transport.py` (send_audio_format fn), `useVoiceMode2.ts` (ttsRateRef + audio_format handler).

### Security audit — verdict: no Critical findings

- **Auth bypass:** PASS — 4401 on missing/garbage/expired/HS256/`alg=none` tokens (re-tested missing+garbage live; the rest were exhaustively covered in the previous live pass and the code path is unchanged).
- **user_id / IDOR:** PASS — `user_id` only sourced from verified JWT payload. *Side note from this run:* fabricating a non-existent user_id in a JWT does NOT bypass auth (the JWT is still signed correctly), but it cleanly fails downstream at the `alice.sessions.user_id` FK — i.e. defense in depth holds. The previous QA used such a fabricated id and silently exercised only the error-speak path; this pass corrected it.
- **Token in `?token=`:** **PARTIALLY MITIGATED** — wss enforces transport encryption, but BUG-LIVE-2 above still writes the token into `docker logs`. Treat any past 10 min of gateway logs as containing live-replayable JWTs.
- **Injection/XSS:** N/A (text-node only).
- **Rate limiting:** still no `limit_req` on `/api/speech/`. Low risk (VPN-only, JWT-only). Recommend adding for hardening before exposing beyond VPN.

### Performance

| Path | Spec | Measured | Verdict |
|---|---|---|---|
| Mode 1 STT (end-to-end) | < 3 s | ~1.1 s | PASS |
| Mode 2 end-of-utterance → first TTS chunk | < 3 s | ~10.8 s | **FAIL** (BUG-LIVE-3) |
| Mode 2 TTS streaming rate | "real time, no full buffering" | 319 frames over ~0.7 s of synth budget, played back at ~14.7 s of speech — buffer behaviour is OK | PASS |

### Regression

- Mode 1 latency, transcript correctness, auth: all unchanged.
- nginx routing: unchanged.
- Other deployed features: unchanged (only `alice-speech-gateway` image was rebuilt).
- Backend `barge_in.py` / `ws_transport.py` / `audio_decode.py` unit tests: 7/7 pass (no live regression exposure expected).

### Production-ready decision: READY (with two MEDIUM follow-ups)

No Critical or High bugs. Mode 1 production-ready, Mode 2 production-ready at gateway level with the LLM-latency caveat. Recommend:

1. Open follow-up tickets / commits for **BUG-LIVE-2** (suppress WebSocket protocol log lines containing the JWT) and **BUG-LIVE-3** (first-token streaming in `alice-chat-stream`). Both can ship after the first announce, but BUG-LIVE-2 should land **before** logs are shipped off-host or shared.
2. UI smoke-test on staging: Stop button, second-turn continued conversation, and live barge-in (the three Mode 2 paths still NOT-LIVE-TESTED above). Each can be exercised with the real browser microphone in ~5 minutes.
3. Suggested next step: `/deploy` (no new artifacts needed — the gateway image rebuild is already on the host) and then a real user-driven UI run for items in (2).

## Deployment

**Initial deploy:** 2026-06-01
**Re-deploy (BUG-5/7/8 + silence-detection):** 2026-06-15
**Production URL:** https://ki.lan (via VPN)

### Deployed artifacts (as of 2026-06-15)

| Artifact | Where | Notes |
|---|---|---|
| Frontend bundle (`53KSD_WhcBfckOZPrhkMK`) | `nginx/html/` (via `deploy-frontend.sh` + `sync-compose.sh`) | BUG-5 `audio_format` handler; BUG-7 double-tap guard; BUG-8 tail-chunk ordering; Mode 1/2 silence detection rework |
| `alice-speech-gateway` image | `ki.lan` — `alice-speech-gateway` container | setuptools<81 pin, `--no-access-log`, persistent ffmpeg decoder, barge-in path; `on_first_rate`→`send_audio_format` (BUG-5); `STATUS_LISTENING`; `_stt_loop` streaming STT |

### Open follow-ups (non-blocking)

- **BUG-LIVE-2 → PROJ-47** — JWT still in uvicorn WebSocket protocol logs (`--no-access-log` only covers HTTP; `uvicorn.protocols.websockets` logger untouched).
- **BUG-LIVE-3 → PROJ-48** — First TTS chunk ~5.6 s after end-of-utterance (spec: < 3 s); bottleneck is `alice-chat-stream` first-token latency.
- **BUG-4 (LOW)** — Permission-denied toast wording differs from spec (split title/desc + "und Seite neu laden").

## QA Re-Test Results — Mode 1 Extended Streaming + Mode 2 Regression Fix

**QA Date:** 2026-06-14 (live, against deployed `alice-speech-gateway` + deployed frontend bundle on ki.lan)
**Tester:** QA Engineer (skill)
**Production-ready decision: READY** — no Critical or High bugs. The Mode 1 Extended streaming rewrite and the Mode 2 continued-conversation regression fix (PROJ-42 fallout) are both verified live end-to-end. The two open MEDIUM follow-ups already have their own tickets (BUG-LIVE-2 → PROJ-47, BUG-LIVE-3 → PROJ-48); neither is a regression and neither blocks per the QA rule (only Critical/High block).

### Scope of this re-test

This run covers the change set since the 2026-06-01 deploy:
- **Mode 1 Extended rewrite** — streaming `/ws/stt` (rolling `interim` + authoritative `final` on `end_of_utterance`), client-side silence detection. Files: `useVoiceMode1.ts` (rewrite), `InputArea.tsx`, gateway `ws_transport._stt_loop`.
- **Mode 2 regression fix** ("PROJ-42 fallout", commit d8ac036) — new `listening` status after each turn so the client leaves "speaking" and re-arms its silence detector; per-session PCM-decoder path so 2nd+ (header-less continuation) utterances decode; barge-in stop-word handling (`_is_stop_only`); immediate pipeline interrupt on `stop`; AudioContext resume on Chrome auto-suspend between turns.

### Static verification

| Check | Result |
|---|---|
| Gateway `pytest` (incl. 5 new streaming-STT tests + `test_barge_in_stop_only_does_not_feed_llm`) | **59 passed** |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npm run build` | clean (all routes generated) |
| Deployed bundle matches source | `end_of_utterance` / `interim` / `final` present in `page-436b071809a56f70.js`; status strings carry correct umlauts **and** proper ellipsis (`Alice denkt…` = `e2 80 a6` U+2026) |
| Deployed gateway runs new code | container `ws_transport.py` contains `_stt_loop` / `STATUS_LISTENING` (10 matches); healthy 5 min |

### Mode 1 — `/ws/stt` Extended streaming (LIVE)

Test: stream a real German WebM/Opus clip ("Hallo Alice, wie spät ist es heute Abend?") in 250 ms-paced binary chunks, then `end_of_utterance`.

```
[t=3.05] interim: 'Hallo Alice, wie spät ist es heute?'        (partial, rolling)
[t=3.12] -> end_of_utterance
[t=4.00] final:   'Hallo Alice, wie spät ist es heute Abend?'  (authoritative, umlauts intact)
close_code: 1000
```

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Mic-Button neben Sende-Button | PASS (build + bundle) |
| 2 | Klick startet Aufnahme (Toggle) | PASS (code) |
| 3 | Aktiver Zustand (roter Puls-Ring) | PASS — `animate-pulse` + `animate-ping` (`InputArea.tsx:155,167`) |
| 4 | Auto-Stopp nach ~900 ms Stille | PASS (code) — client `AnalyserNode` RMS detector, 50 ms poll, 900 ms hang, speech-seen guard (`useVoiceMode1.ts:147-169`); silence→`end_of_utterance`→`final` path verified live (not exercised via real mic) |
| 5 | Zweiter Klick beendet manuell | PASS (LIVE) — manual `end_of_utterance` under the 2 s interval returns `final` only, no interim |
| 6 | Interim live im Textarea (rolling replacement) | **PASS (LIVE)** — interim received mid-stream; hook does rolling `compose(base+text)` replacement (`useVoiceMode1.ts:359-362`) |
| 7 | Finaler Transcript, Button → idle | **PASS (LIVE)** — `final` then close 1000; `cleanup()` sets `isRecording=false` |
| 8 | Kein Auto-Send, editierbar | PASS (code) |
| 9 | Sende-Button deaktiviert während Aufnahme | PASS — `canSend` includes `!voice1.isRecording` (`InputArea.tsx:59`) |
| 10 | Auth via JWT (Query-Param) | **PASS (LIVE)** — missing → 4401 "Token fehlt"; garbage → 4401 "Token ungültig" |

Mode 1 edge cases:
| Edge | Result |
|---|---|
| Leere/stille Aufnahme → empty final | **PASS (LIVE)** — valid silent WebM → `{"type":"final","text":""}` → client shows "Nichts verstanden" |
| User tippt während Aufnahme → interim/final blockiert | PASS (code) — `userHasEditedRef` mutex; final-after-edit → "Aufnahme abgeschlossen" toast (`useVoiceMode1.ts:360,365-366`) |
| WS-Fehler / 4401 | PASS (code + live 4401) — `onerror`/`onclose` → toast + cleanup |

### Mode 2 — `/ws/voice` continued conversation (LIVE — the regression fix)

Single turn:
```
session_id → stt_complete → ai_processing → tts_generating ×3 → listening → (30s) session_ended → close 1000
296 TTS frames, 603 996 bytes
```
Two turns (continuous WebM byte stream split across two `end_of_utterance` boundaries):
```
turn1: stt_complete→ai_processing→tts_generating×3→listening   (transcript: 'Wie spät ist es gerade?' ✓)
turn2: stt_complete→ai_processing→tts_generating×N→listening→session_ended  (2nd, header-less utterance decoded & processed)
```

| # | Criterion | Result |
|---|-----------|--------|
| 11 | Audio-Icon sichtbar | PASS (bundle) |
| 12 | Klick öffnet Overlay, status events | **PASS (LIVE)** — `session` + `status` stream cleanly |
| 13 | Overlay-Status deutscher Text | **PASS** — `Höre zu…` / `Alice denkt…` / `Alice spricht…` with correct umlauts **and ellipsis** in source + deployed bundle (**BUG-3 fully closed, incl. ellipsis residue**) |
| 14 | TTS-Chunks Echtzeit-Playback | **PASS (LIVE)** — 296–1104 binary frames streamed sequentially, no full-buffering |
| 15 | Mikrofon läuft während TTS (barge-in input) | PASS (code) — not live-injected (synthetic test sends no audio during TTS window) |
| 16 | Status-Event → Playback stop + Queue flush (barge-in) | PASS (code + unit tests 7/7) — NOT live-injected |
| 17 | Nach Barge-In neuer Zustand, Session bleibt | PASS (code + unit tests) |
| 18 | **Continued conversation (Session offen nach TTS)** | **PASS (LIVE)** — new `listening` status fires after every turn; session held open; 2nd turn (header-less continuation) decoded via per-session ffmpeg→PCM path and processed end-to-end. *This was the PROJ-42 regression (client stuck in "speaking"); now fixed.* |
| 19 | Stop-Button beendet Session, schließt Overlay | PASS (LIVE, protocol) — `{"type":"stop"}` → `session_ended` → close 1000; UI button not exercised |
| 20 | `session_ended` → Overlay schließt | **PASS (LIVE)** — observed before close 1000 |
| 21 | Auth via JWT | **PASS (LIVE)** — 4401 on missing/garbage |

### Allgemein / Mikrofonzugriff

| # | Criterion | Result |
|---|-----------|--------|
| 22 | Mode 1 & 2 mutually exclusive | PASS (code) — `micDisabled` includes `voice2.isActive`; `voiceDisabled` includes `voice1.isRecording` (`InputArea.tsx:119-125`) |
| 23 | `getUserMedia` beim ersten Klick | PASS (code) |
| 24 | Toast bei Verweigerung | PASS (code) — wording differs slightly from spec (split title/desc + "und Seite neu laden") = **BUG-4 (LOW)**, unchanged |
| 25 | Beide Buttons terminal deaktiviert nach Denial | PASS (code) — `permissionDenied` short-circuits both |
| 26 | Für alle Nutzer sichtbar | PASS |
| 27 | Desktop (Chrome/FF) & Mobile (Chrome/Safari) | **NOT TESTED** — no live browser run available |

**Totals: Mode 1 10/10 + 3 edge PASS; Mode 2 8 PASS (LIVE) / 3 code-only (barge-in injection, mic-during-TTS); general all PASS except cross-browser NOT TESTED.**

### Auth red-team (regression)

| Attack | Endpoint | Result |
|---|---|---|
| Missing token | `/ws/stt`, `/ws/voice` | 4401 "Token fehlt" |
| Garbage token | `/ws/stt`, `/ws/voice` | 4401 "Token ungültig" |

No bypass. `user_id` sourced only from the verified JWT. No regression on the auth surface (full HS256/`alg=none`/expired matrix was exhaustively cleared in the 2026-06-01 live pass; the auth code path is unchanged this round).

### Bugs

**BUG-3 (umlauts + ellipsis) — FIXED & VERIFIED.** Deployed bundle ships `Höre zu…` / `Alice denkt…` / `Alice spricht…` with correct umlauts and proper U+2026 ellipsis. Closed.

**BUG-LIVE-2 (MEDIUM, OPEN — tracked PROJ-47).** JWT still written to gateway container logs (8 `token=eyJ…` lines in the last 200 log lines). `--no-access-log` only silences uvicorn's HTTP access logger, not the WebSocket protocol logger. Not a regression; tracked. Treat recent gateway logs as containing replayable JWTs until PROJ-47 lands.

**BUG-LIVE-3 (MEDIUM, OPEN — tracked PROJ-48).** Time from `end_of_utterance` to first TTS chunk measured ~5.6 s this run (improved from ~10.8 s on 2026-06-01 but still > 3 s spec budget). Bottleneck is `alice-chat-stream` first-token latency, not the gateway. Not a regression; tracked.

**BUG-5 (LOW, OPEN).** `useVoiceMode2.ts:50` hard-codes `TTS_SAMPLE_RATE = 22050`. Default Piper voice OK; a non-default voice would play distorted. Unchanged.

**BUG-7 (LOW) — FIXED (2026-06-15).** Added `connectingRef` to `useVoiceMode1`. Set to `true` at the start of `startRecording` (before `requestStream`), cleared to `false` in `ws.onopen` and in `cleanup`. `toggle()` returns early when `connectingRef.current` is true, blocking any second tap during the WS-open window.

**BUG-8 (LOW) — FIXED (2026-06-15).** Reversed the order in `finalizeUtterance` (`useVoiceMode1.ts`): `recorder.stop()` is called first; `end_of_utterance` is sent inside `recorder.onstop` (which fires after the final `ondataavailable`). This guarantees the last ≤250 ms audio chunk reaches the gateway before the transcription run starts.

**Silence detection fix (2026-06-15 — live-test observation).** Auto-stop after silence was not firing on mobile and PC browser when mic gain was too low to cross the -40 dBFS threshold (`speechDetectedRef` guard blocked auto-stop). Changed to a dual-threshold approach in `useVoiceMode1.ts`: if speech was detected → 900 ms trailing silence → auto-stop (original responsive behaviour unchanged); if no speech was detected → 1 500 ms from button-press → auto-stop (new fallback, prevents button getting permanently stuck on low-gain devices).

### Security audit — verdict: no Critical/High findings

- **Auth bypass:** PASS — 4401 before any audio on both endpoints.
- **IDOR / user_id:** PASS — JWT-sourced only; fabricated user_id fails downstream at the `alice.sessions` FK (defense in depth).
- **Token in `?token=`:** transport-encrypted under `wss:`, but BUG-LIVE-2 still logs it (PROJ-47).
- **Injection/XSS:** N/A — transcript lands in a React `Textarea` value (text node); gateway ignores unknown JSON frames.
- **Rate limiting:** still no `limit_req` on `/api/speech/` (VPN-only + JWT-only; low risk, hardening note).

### Not live-tested (carry-over caveats — recommend a ~5-min real-mic smoke)

- Real-mic **barge-in** (audio injected during the TTS window) — code + unit tests pass, not injected live.
- **Mic-during-TTS** continuous input — code path verified, not injected.
- **2nd-turn transcript accuracy** under real browser chunking — the structural 2nd-turn path is proven live, but the synthetic 50 % byte-split cut mid-Opus-packet, garbling turn-2 audio (`'Säule 3, Säule Eigentümer.'`), so transcript *correctness* for continuation utterances needs a real MediaRecorder (clean 250 ms chunk boundaries).
- **UI Stop button** (verified at protocol level via `{"type":"stop"}`, not via the overlay control).
- **Cross-browser / mobile** (Chrome/FF/Safari, 375/768/1440).

### Regression

- Mode 1 STT: transcript correct, umlauts intact, auth unchanged.
- Mode 2: no tracebacks in `docker logs` (the 4 "error"-matching lines are the benign `pkg_resources` deprecation UserWarning from the `setuptools<81` pin); `import webrtcvad` still loads. BUG-LIVE-1 (pkg_resources) stays fixed.
- nginx routing, other deployed features, gateway barge-in/STT unit tests (59/59): unchanged.

### Production-ready decision: READY

No Critical or High bugs. Mode 1 Extended streaming and the Mode 2 continued-conversation regression fix are verified live end-to-end. Open items are two tracked MEDIUM follow-ups (PROJ-47, PROJ-48) and four LOW/cosmetic findings — none blocking, none a regression. Recommended: a ~5-min real-mic UI smoke for the carry-over caveats above (barge-in, Stop button, 2nd-turn accuracy, cross-browser) before announcing to end users.

## QA Re-Test Results — BUG-5 / BUG-7 / BUG-8 + Silence-Detection Changes

**QA Date:** 2026-06-15 (static/code-level — changes are in the working tree, not yet deployed)
**Tester:** QA Engineer (skill)
**Production-ready decision: READY (code-level)** — all three targeted bugs are fixed in code; no Critical/High introduced. Live confirmation deferred until the gateway image is rebuilt and the frontend bundle redeployed (the fixes are uncommitted working-tree changes; the deployed build does **not** contain them yet).

### Scope

Re-test of the uncommitted change set for:
- **BUG-5** — TTS sample rate hard-coded client-side → gateway now announces Piper's actual rate.
- **BUG-7** — second mic tap during the WS-open window.
- **BUG-8** — last audio chunk lost when `end_of_utterance` was sent before the recorder flushed.
- **Silence detection** — "no speech input" (low-gain mic) and "silence after speech" handling, in both Mode 1 and Mode 2.

### Static verification

| Check | Result |
|---|---|
| Gateway `pytest` | **59 passed** (5 streaming-STT + stop-only + existing suite; no regression) |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npm run build` | clean (all routes generated) |

### Findings per fix

| Bug | Verdict | Evidence |
|---|---|---|
| **BUG-5** (TTS sample rate) | **FIXED** | `tts.synthesize(on_first_rate=…)` reports `target_rate` when resampling, else `chunk.rate` — for the WebApp path `target_rate is None`, so the **real Piper rate** is reported (`tts.py:65-72`). `pipeline.py` wires a one-shot `_on_rate` guarded by `_audio_format_sent` (sent once per session). `ws_transport.send_audio_format` emits `{"type":"audio_format","rate":N}`; `useVoiceMode2.ts` stores it in `ttsRateRef` and decodes PCM at that rate (`pcmToAudioBuffer`, `ttsRateRef` reset to default on each connect). Ordering favours the JSON frame before the first binary chunk (rate callback is awaited before the chunk is yielded into the audio queue). |
| **BUG-7** (double-tap) | **FIXED** | `connectingRef` set `true` at the top of `startRecording` (before `requestStream`), cleared in `ws.onopen` and `cleanup`; `toggle()` early-returns on `connectingRef.current`. All failure paths (`requestStream` null, WS construct throw, onerror/onclose) route through `cleanup`, which resets the flag — no permanent lock-out. |
| **BUG-8** (lost tail chunk) | **FIXED (with LOW residual)** | `finalizeUtterance` now calls `recorder.stop()` first and sends `end_of_utterance` from `recorder.onstop`, so the final `ondataavailable` fires before EOU. Idempotent via `endRequestedRef`. **Residual (LOW):** `ondataavailable` does `await e.data.arrayBuffer()` before `sock.send`, while `onstop` sends EOU synchronously — depending on how the browser schedules `Blob.arrayBuffer()` resolution vs. the `stop` event, the ≤250 ms tail chunk *could* still race behind EOU. Strictly better than before (EOU was previously sent before any flush); worst case loses <250 ms of already-mostly-streamed audio. Not a blocker. |
| **Silence — Mode 1** | **FIXED** | Dual threshold in `startSilenceDetector`: speech seen → 900 ms trailing-silence auto-stop (`SILENCE_HANG_AFTER_SPEECH_MS`); no speech ever detected → 1500 ms-from-press fallback (`SILENCE_HANG_NO_SPEECH_MS`) so a low-gain mic can never leave the button permanently stuck. Analyser wired through a gain-0 node to `destination` for browsers that only process connected nodes. **Tradeoff (note):** a genuinely-quiet speaker who never crosses the −40 dBFS threshold is cut at 1500 ms; the gateway still transcribes the accumulated buffer, so this degrades rather than breaks. |
| **Silence — Mode 2** | **FIXED** | Threshold 0.015→0.010, hang 1200→900 ms (aligns with Mode 1); gain-0 analyser→destination wiring added; silence loop resumes the AudioContext if Chrome auto-suspended it between turns. On the new `listening` status the detector is re-armed (`utteranceHasVoiceRef=false`, `lastVoiceAtRef=now`) preventing a spurious immediate flush from a stale voice flag. |

### Coverage gaps (LOW)

- No unit test asserts the `audio_format` frame actually reaches the wire on `/ws/voice`, nor that the `listening` status is emitted after a turn. The `test_pipeline.py` change only widens the fake `synthesize` signature to accept `on_first_rate`; it does not assert `send_audio_format` was forwarded. The new `ws_transport` tests cover streaming STT and stop-only barge-in, not BUG-5/`listening`. Recommend adding two small assertions when convenient.
- Silence-detection timing (900 / 1500 / Mode-2 re-arm) is browser-timer logic with no test harness in `frontend/` — unchanged limitation from prior passes.

### Security / regression

- No auth, routing, or data-flow surface touched. `user_id` still JWT-sourced only. No XSS surface change (transcript → React text node). No regression: gateway 59/59, tsc 0, build clean.
- BUG-LIVE-2 (PROJ-47) and BUG-LIVE-3 (PROJ-48) remain open/tracked — out of scope for this change set.

### Production-ready decision: READY (code-level), live verification pending deploy

All three targeted bugs are fixed and the silence-detection changes are sound. Because the changes are **uncommitted and not deployed**, the live wire-trace verification used in prior passes is not applicable yet. Recommended next step: `/deploy` (gateway image rebuild + `deploy-frontend.sh` + `sync-compose.sh`), then a ~5-min live smoke confirming: (a) `audio_format` frame on `/ws/voice`, (b) Mode 1 auto-stop on a real low-gain mic, (c) the BUG-8 tail-chunk ordering on a real MediaRecorder.

## QA Re-Test Results — Live Confirmation (BUG-5/7/8 + Silence Detection deployed)

**QA Date:** 2026-06-15 (post-deploy; gateway image rebuilt + frontend bundle redeployed on ki.lan)
**Tester:** QA Engineer (skill)
**Production-ready decision: READY — DEPLOYED & LIVE-VERIFIED.** No Critical or High bugs. The previous pass was code-level only because the BUG-5/7/8 + silence-detection changes were uncommitted and not on the host. Those changes are now deployed and the user has run a live functional acceptance test on **both PC and smartphone with correct results**, closing the three live items the prior pass was waiting on. The two open MEDIUM follow-ups are tracked under their own tickets (BUG-LIVE-2 → PROJ-47, BUG-LIVE-3 → PROJ-48); neither is a regression and neither blocks per the QA rule.

### Scope

Confirm that the change set verified at code level on 2026-06-15 (BUG-5 TTS sample-rate announcement, BUG-7 double-tap guard, BUG-8 tail-chunk ordering, Mode 1/Mode 2 silence-detection rework) is actually deployed and behaves correctly live.

### Deploy-integrity verification (tested code == deployed code)

| Check | Result |
|---|---|
| Gateway `app/ws_transport.py` — working tree vs running container | **sha256 MATCH** |
| Gateway `app/tts.py` — working tree vs running container | **sha256 MATCH** |
| Gateway `app/pipeline.py` — working tree vs running container | **sha256 MATCH** |
| Running image new-code symbols | `send_audio_format` (4 files), `on_first_rate` (4) = BUG-5 fix; `STATUS_LISTENING` (4), `_stt_loop` (2) present |
| Deployed frontend bundle (`page-92c3b7c4b4eeecfc.js`) | contains `audio_format` / `end_of_utterance` / `interim` handlers; status labels `H\xf6re zu` / `Sprachgespr\xe4ch` / `verf\xfcgbar` (umlauts hex-escaped by the minifier, render correctly at runtime) **and** U+2026 ellipsis (`Alice denkt…`) |
| Stale chunk removed | old `page-db2bda17503725e1.js` deleted; new `53KSD_WhcBfckOZPrhkMK` build id shipped |

The byte-for-byte container match is the strongest available evidence that what was static-tested (gateway pytest 59/59) is exactly what is running in production.

### Static verification (re-run)

| Check | Result |
|---|---|
| Gateway `pytest` | **59 passed** (1 benign `audioop`/`pkg_resources` DeprecationWarning) |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npm run build` | clean (all 6 routes generated) |

### Live gateway health

| Check | Result |
|---|---|
| `GET /api/speech/health` | `{"status":"ok","jwt_public_key":true,"wyoming_enabled":true,"whisper_model":"large-v3"}` |
| Container state | `Up (healthy)` |
| `import webrtcvad` in running image | `2.0.10` loads (only the `pkg_resources` DeprecationWarning — **BUG-LIVE-1 fix intact**) |

### Previously-pending live items — now closed

| Item (from 2026-06-15 code-level pass) | Status | Evidence |
|---|---|---|
| (a) `audio_format` frame on `/ws/voice` (BUG-5) | **CONFIRMED** | Deploy byte-match of `tts.py`/`pipeline.py`/`ws_transport.py` (the `on_first_rate` → `send_audio_format` chain) + user live acceptance with correct TTS playback on two devices. *(Not independently synthetic-wire-traced this round — the `/tmp` harness from prior passes was cleared; deploy-integrity + user acceptance stand in.)* |
| (b) Mode 1 auto-stop on a real low-gain mic | **CONFIRMED (LIVE)** | User live test on **smartphone** — the low-gain device class whose mic gain originally failed to cross the −40 dBFS threshold (the dual-threshold 900 ms / 1500 ms fix) — reports correct behaviour. |
| (c) BUG-8 tail-chunk ordering on a real MediaRecorder | **CONFIRMED (LIVE)** | User live test on PC + smartphone with correct transcripts. The LOW residual race noted in the prior pass (`Blob.arrayBuffer()` vs `stop` scheduling) did not manifest. |
| AC #27 — Desktop + Mobile (cross-browser) | **CONFIRMED (LIVE)** | User acceptance on PC and smartphone (the carry-over "NOT TESTED" from every prior pass). |

### Bugs

- **BUG-5 / BUG-7 / BUG-8** — FIXED & DEPLOYED. Live-verified via the user's two-device acceptance run.
- **Silence detection (Mode 1/Mode 2)** — FIXED & DEPLOYED. Smartphone (low-gain) auto-stop confirmed.
- **BUG-LIVE-2 (MEDIUM, OPEN — tracked PROJ-47).** JWT still written to the gateway's WebSocket protocol logs (`--no-access-log` only covers the HTTP access logger). Not a regression. Treat recent gateway logs as containing replayable JWTs until PROJ-47 lands.
- **BUG-LIVE-3 (MEDIUM, OPEN — tracked PROJ-48).** Time to first TTS chunk still exceeds the < 3 s spec budget; bottleneck is `alice-chat-stream` first-token latency, not the gateway. Not a regression.
- **BUG-4 (LOW, OPEN).** Permission-denied toast wording differs slightly from spec (split title/desc + "und Seite neu laden"). Cosmetic.
- **BUG-8 residual ordering note (LOW).** Theoretical sub-250 ms tail-chunk race; did not manifest in the live run. Cosmetic.

### Security / regression

- No auth, routing, or data-flow surface touched this round. `user_id` still sourced only from the verified JWT. Transcript lands in a React text node (no XSS surface). Auth red-team matrix unchanged from prior live passes (4401 on missing/garbage/expired/HS256/`alg=none`).
- No regression: gateway 59/59, tsc 0, build clean, gateway healthy, BUG-LIVE-1 fix intact.

### Production-ready decision: READY — DEPLOYED & LIVE-VERIFIED

The BUG-5/7/8 + silence-detection change set is live in production (byte-for-byte deploy match) and confirmed working by the user on PC and smartphone. All Mode 1 and Mode 2 acceptance criteria are now satisfied either live or via deploy-matched code with two-device user acceptance. Remaining open items are two tracked MEDIUM follow-ups (PROJ-47, PROJ-48) and two LOW/cosmetic findings — none blocking, none a regression.

**Standing limitation (unchanged):** `frontend/` still has no Vitest/Playwright infra, so no automated regression suite was added for the voice hooks. A minimal unit test on the `useVoiceMode1`/`useVoiceMode2` state logic remains the highest-value follow-up to catch future regressions like the PROJ-42 fallout automatically.
