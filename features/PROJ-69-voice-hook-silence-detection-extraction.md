# PROJ-69: Voice-Hooks — Silence-Detection-Extraktion

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- Required by: PROJ-70 (Adaptiver Noise-Floor) — baut auf dem hier extrahierten gemeinsamen Hook auf.
- Betrifft `useVoiceMode1.ts` (Push-to-Talk) und `useVoiceMode2.ts` (Vollduplex), Teil von PROJ-41 (Deployed).

## User Stories
- Als Entwickler möchte ich die nahezu identische AudioContext/AnalyserNode-RMS-Silence-Detection-Logik aus `useVoiceMode1.ts` und `useVoiceMode2.ts` an einer Stelle pflegen, statt sie doppelt zu warten.
- Als Nutzer soll sich am Verhalten beider Sprachmodi (Push-to-Talk und Vollduplex) durch diesen Refactor nichts ändern — identische Schwellenwerte, identisches Timing.

## Acceptance Criteria
- [ ] Ein gemeinsamer Hook/Util (z. B. `hooks/useSilenceDetector.ts`) kapselt: `AudioContext`/`AnalyserNode`-Setup aus einem `MediaStream`, RMS-Berechnung via `getFloatTimeDomainData`, Interval-basiertes Polling, Aufräumen (Interval-Clear, AudioContext-Close).
- [ ] Der gemeinsame Hook ist konfigurierbar genug, um beide bestehenden Verhaltensweisen exakt zu reproduzieren:
  - `useVoiceMode1.ts`: zweistufiges Hang-Timing (`SILENCE_HANG_AFTER_SPEECH_MS=900`, `SILENCE_HANG_NO_SPEECH_MS=1500`), 50ms-Check-Intervall.
  - `useVoiceMode2.ts`: einstufiges Hang-Timing (`SILENCE_HANG_MS=900`), 100ms-Check-Intervall, inkl. Resume eines suspendierten `AudioContext` während des Pollings.
- [ ] `SILENCE_THRESHOLD` (0.01 linear RMS, ≈ -40 dBFS) bleibt in beiden Modi unverändert und ist im gemeinsamen Hook zentral definiert statt zweimal dupliziert.
- [ ] `useVoiceMode1.ts` und `useVoiceMode2.ts` nutzen beide den gemeinsamen Hook; die modusspezifische Logik (was bei Stille passiert: Auto-Stop vs. `end_of_utterance`-Nachricht) verbleibt in den jeweiligen Hooks.
- [ ] Kein Verhaltensunterschied vor/nach dem Refactor: gleiche Schwellenwerte, gleiche Timings, gleiche Edge-Case-Behandlung (fehlgeschlagene `AudioContext`-Erstellung, suspendierter Context).
- [ ] Bestehende manuelle/QA-Testfälle für PROJ-41 (Push-to-Talk-Aufnahme, Vollduplex-Gespräch, Barge-in) bleiben ohne Regression bestehen.

## Edge Cases
- `AudioContext`-Erstellung schlägt fehl (z. B. Browser-Policy): bestehendes `try/catch` mit `console.warn` bleibt erhalten, keine neue Fehlerbehandlung nötig.
- Schnelles Start/Stop-Toggling des Mikrofons: keine geleakten Intervals/AudioContexts — Cleanup-Verhalten identisch zu heute.
- Suspendierter `AudioContext` (Mode 2): Resume-Logik bleibt spezifisch für Mode 2 erhalten, ohne dass Mode 1 dieses Verhalten aufgezwungen bekommt.
- Browser ohne `AudioContext`-Support (sehr alte Browser, außerhalb der unterstützten Matrix Chrome/Firefox/Safari): unverändertes bestehendes Fallback-Verhalten.

## Technical Requirements (optional)
- Reiner Frontend-Refactor, keine Backend-/Protokoll-Änderung (Wyoming/WebSocket-Nachrichtenformate bleiben unangetastet).
- Extraktion sollte als reine Funktions-/Hook-Signatur erfolgen, die von `/architecture` final festgelegt wird (z. B. Callback-basiert vs. Status-Rückgabe).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
