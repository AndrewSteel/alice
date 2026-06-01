# PROJ-41: WebApp Voice Interface

## Status: Approved
**Created:** 2026-05-28
**Last Updated:** 2026-06-01 (live re-test passed — Mode 1 & Mode 2 happy paths verified end-to-end; BUG-LIVE-1 fixed; BUG-LIVE-2 reopened — `--no-access-log` does not suppress uvicorn's WS protocol logger so JWTs are still in container logs; BUG-LIVE-3 new — first-TTS latency ~10.8 s vs 3 s spec budget, alice-chat-stream first-token; both MEDIUM, neither blocks)

## Dependencies
- Requires: PROJ-40 (Speech Gateway Service) — WebSocket endpoints `/ws/stt` (Mode 1) and `/ws/voice` (Mode 2) on `/api/speech/`
- Requires: PROJ-1 (User Authentication) — JWT token for WebSocket auth

## User Stories

- Als Nutzer möchte ich einen Mikrofon-Button neben dem Sende-Button drücken, sprechen und den transkribierten Text im Eingabefeld sehen, damit ich Nachrichten per Sprache eingeben kann ohne tippen zu müssen.

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
- [ ] Ein zweiter Klick auf den aktiven Mikrofon-Button beendet die Aufnahme und sendet das Audio an `/ws/stt`
- [ ] Der transkribierte Text erscheint im Textarea-Eingabefeld
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

- **Leere Aufnahme (Mode 1)**: Whisper liefert leeren Text → kein Text ins Eingabefeld einfügen; optional Toast "Nichts verstanden, bitte nochmals versuchen"
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
- **WebSocket-Endpunkte**: `/api/speech/ws/stt` (Mode 1), `/api/speech/ws/voice` (Mode 2) — über nginx proxy zu `alice-speech-gateway:10301`
- **Performance**: Erste TTS-Audio-Wiedergabe beginnt innerhalb von < 3s nach Ende der Spracheingabe (Gateway-Budget; Frontend-Overhead < 100ms)
- **Browser-Support**: Chrome 90+, Firefox 90+, Safari 15+ (iOS), Chrome Android
- **Kein neuer API-Endpunkt** nötig — kommuniziert ausschließlich über den bestehenden Gateway-WebSocket

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

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
MicButton click → getUserMedia → MediaRecorder starts
→ MicButton click again → stop → single blob sent over WebSocket
→ Gateway returns JSON { text: "..." } → injected into Textarea
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
Mode 1: isRecording: boolean, transcript callback
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

**BUG-5 (LOW, UNCHANGED).** TTS sample rate hard-coded to 22050 Hz client-side. Not exercised (default Piper voice in use). **P3.**

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

**Deployed:** 2026-06-01
**Production URL:** https://ki.lan (via VPN)

### Deployed artifacts

| Artifact | Where | Notes |
|---|---|---|
| Frontend bundle | `nginx/html/` (via `deploy-frontend.sh` + `sync-compose.sh`) | Voice buttons + VoiceOverlay in chat UI |
| `alice-speech-gateway` image | `ki.lan` — `alice-speech-gateway` container | setuptools<81 pin, `--no-access-log`, persistent ffmpeg decoder, barge-in path |

### Known follow-ups (non-blocking)

- **BUG-LIVE-2** — JWT still appears in uvicorn WebSocket protocol logs; `--no-access-log` only covers HTTP. Fix: filter or silence `uvicorn.protocols.websockets.websockets_impl` logger.
- **BUG-LIVE-3** — First TTS chunk arrives ~10.8 s after end-of-utterance (vs 3 s spec budget). Bottleneck: `alice-chat-stream` first-token latency (qwen3:14b on 3090). Fix: stream first sentence as soon as it's ready.
- UI smoke on staging still pending for: Stop button, second conversation turn, live barge-in.
