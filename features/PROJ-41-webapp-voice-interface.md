# PROJ-41: WebApp Voice Interface

## Status: Planned
**Created:** 2026-05-28
**Last Updated:** 2026-05-28

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
- **Barge-In aus Browser-Sicht (Mode 2)**: Während TTS-Audio läuft nimmt der Browser weiterhin Mikrofon-Audio auf und sendet es an den Gateway — das Overlay zeigt weiterhin "Alice spricht…" bis der Gateway antwortet; kein besonderer UI-Zustand für Barge-In nötig
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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
