# PROJ-41: WebApp Voice Interface

## Status: Planned
**Created:** 2026-05-28
**Last Updated:** 2026-05-28 (Barge-In ergänzt)

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

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
