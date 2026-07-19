# PROJ-69: Voice-Hooks — Silence-Detection-Extraktion

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- New `frontend/src/hooks/useSilenceDetector.ts` shared by `useVoiceMode1.ts` (50ms interval, two-stage hang, no resume) and `useVoiceMode2.ts` (100ms interval, single-stage hang, resume-on-suspend). Mode-specific silence semantics (auto-stop vs. `end_of_utterance`) stay in each caller's `onSample` callback.
- `AudioContext.close()` deliberately stays caller-owned, not moved into the shared hook's `stop()` — Mode 2 reuses the same context for TTS playback.
- QA: READY, 0 bugs. Live microphone/browser E2E not performed (not feasible headlessly); code-level behavioral-equivalence verified instead. Recommend a real-hardware smoke test pre-deploy.

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

#### A) Component Structure

```
hooks/useSilenceDetector.ts (neu)
+-- AudioContext/AnalyserNode-Setup aus einem MediaStream
+-- RMS-Berechnung (getFloatTimeDomainData), Interval-basiertes Polling
+-- konfigurierbar: Check-Intervall, Hang-Timing (ein- oder zweistufig), Resume-Verhalten bei suspendiertem Context
+-- Cleanup (Interval-Clear, AudioContext-Close)

useVoiceMode1.ts → nutzt Hook mit: 50ms-Intervall, zweistufiges Hang-Timing (900ms nach Sprache / 1500ms ohne Sprache), kein Resume
useVoiceMode2.ts → nutzt Hook mit: 100ms-Intervall, einstufiges Hang-Timing (900ms), Resume bei suspendiertem Context während des Pollings
```

#### B) Data Model

Keine — reiner clientseitiger Refactor, kein persistenter oder Server-Zustand.

#### C) Tech Decisions

- **Konfigurationsfläche statt zwei separater Hooks:** Die Spec verlangt exakte Reproduktion beider bestehender Verhaltensweisen — der gemeinsame Hook nimmt die Unterschiede (Intervall, Hang-Timing-Form, Resume-Flag) als Parameter, statt ein Verhalten hart zu codieren und das andere als Sonderfall zu behandeln.
- **`SILENCE_THRESHOLD` (0.01 linear RMS, ≈ -40dBFS) zentral im gemeinsamen Hook definiert** — heute wortgleich in beiden Dateien dupliziert; das ist die eigentliche Duplikation, die diese Spec adressiert.
- **Callback- vs. Status-Rückgabe-Signatur bewusst offen für `/frontend`** (laut Technical Requirements der Spec) — architektonisch relevant ist nur, dass modusspezifisches Verhalten (Auto-Stop vs. `end_of_utterance`-Nachricht) in den jeweiligen Hooks verbleibt, nicht im gemeinsamen.
- **Direkte Grundlage für PROJ-70:** Das dort ergänzte Kalibrierungsfenster ist eine natürliche Erweiterung dieses Hooks (eine weitere konfigurierbare Stufe vor dem aktiven RMS-Schwellwert-Check), keine parallele Implementierung — deshalb muss diese Spec zuerst landen.
- **Kein Protokoll-/Backend-Bezug:** Wyoming-/WebSocket-Nachrichtenformate bleiben unangetastet, reine Client-Refaktorierung.

#### D) Dependencies

Keine neuen Pakete.

## QA Test Results

**Tested:** 2026-07-19
**Tester:** QA Engineer (AI)
**Scope:** Pure client-side refactor — extraction of shared `useSilenceDetector.ts` from `useVoiceMode1.ts` (push-to-talk) and `useVoiceMode2.ts` (full-duplex). Bar = "zero behavior change vs. pre-refactor," not new functionality.
**Method:** Full read of the three hook files + line-by-line `git diff HEAD -- frontend/src/hooks/` behavioral-equivalence audit, `next build` (type-check + prod build), `tsc --noEmit` project-wide, caller regression scan.

### Verification Evidence
- `git diff HEAD` shows Mode 1/Mode 2 changes are exclusively: (a) import of `SILENCE_THRESHOLD`/`useSilenceDetector`, (b) deletion of local `analyserRef`/`analyserSourceRef`/`silenceIntervalRef` + inline `start/stopSilenceDetector`, (c) their replacement by the shared hook with the per-tick decision moved verbatim into `handleSilenceSample`. No changes to WS wire protocol, message handling, timings, thresholds, return types, or option interfaces.
- `npm run build`: PASS (compiled + type-checked + static export; see note on transient dms.ts failure below).
- `tsc --noEmit` (project tsconfig): **0 errors** across the whole frontend.
- Return API of both hooks unchanged → caller `InputArea.tsx` compiles and uses `voice1.isRecording` / `voice2.isActive` exactly as before.

### Acceptance Criteria Status

#### AC-1: Shared hook encapsulates AnalyserNode setup / RMS / interval polling / cleanup — PASS
- [x] `AudioContext`/`AnalyserNode` setup from a `MediaStream` (`start(stream, ctx)` → `createAnalyser`, `fftSize=1024`, `createMediaStreamSource`, gain-0 wiring to destination) — identical to both originals.
- [x] RMS via `getFloatTimeDomainData` + `sqrt(sumSq/len)` — byte-identical math.
- [x] Interval-based polling via `setInterval(checkIntervalMs)`.
- [x] Cleanup: interval-clear → source `disconnect()` (in try/catch) → null refs.
- [NOTE] `AudioContext.close()` is intentionally NOT performed inside the shared hook — the AudioContext stays caller-owned (as it was pre-refactor). This is correct and load-bearing: in Mode 2 the same AudioContext also drives TTS playback, so closing it in the detector's `stop()` would kill playback. The architecture doc's cleanup wording ("...AudioContext-Close") is looser than the implementation; keeping close() with the caller preserves original behavior and is the right call. Not a bug.

#### AC-2: Configurable to reproduce both behaviors exactly — PASS
- [x] Mode 1: `checkIntervalMs: 50`, two-stage hang (`900` after speech / `1500` no-speech) implemented in `handleSilenceSample`, `resumeOnSuspend` off. Matches original.
- [x] Mode 2: `checkIntervalMs: 100`, single-stage hang (`900`), `resumeOnSuspend: true` (resumes suspended context during polling). Matches original.
- [NOTE] Mode-specific hang math lives in each caller's `onSample` (per Tech Design C); the shared hook supplies interval + resume + per-tick RMS. Reproduction is exact.

#### AC-3: `SILENCE_THRESHOLD` = 0.01 centralized — PASS
- [x] Defined once as `export const SILENCE_THRESHOLD = 0.01` in `useSilenceDetector.ts`; both modes import it. Removed from both callers (was `0.01` in Mode 1, `0.010` in Mode 2 — numerically identical). No duplication remains.

#### AC-4: Both modes use the shared hook; mode-specific silence semantics stay in the callers — PASS
- [x] Mode 1: silence → `finalizeRef.current()` (auto-stop) inside `handleSilenceSample`.
- [x] Mode 2: silence → `ws.send({type:"end_of_utterance"})` + no-speech-session-end → `stopRef.current()`, all inside its `handleSilenceSample`.
- [x] Shared hook contains only the detection mechanism; no `end_of_utterance`/auto-stop knowledge.

#### AC-5: No behavior difference pre/post refactor — PASS
- [x] Same threshold (0.01), same timings (900/1500/50ms, 900/100ms), same gain-0 graph wiring.
- [x] Resume-on-suspend isolated to Mode 2 via `resumeOnSuspend` (default `false` → Mode 1 never resumes, matching original which had no resume branch).
- [x] Failed-`AudioContext`-creation `try/catch` + `console.warn` remains in the callers (the hook does not create the context), unchanged.
- [x] Single `performance.now()` per tick passed to `onSample` and used for both voice-mark and hang comparison — same as original which captured `now` once per tick.
- [x] Added guard `if (!analyserNode || !activeCtx) return;` in the shared interval is a superset of Mode 1's original `if (!analyserNode) return;`; `activeCtx` is only nulled in `stop()` which also clears the interval, so no observable divergence.

#### AC-6: PROJ-41 manual test cases (push-to-talk, full-duplex, barge-in) — no regression — PASS (by code equivalence; live manual E2E not performed)
- [x] Code paths for recording start/stop, `end_of_utterance`, barge-in flush, and no-speech auto-close are unchanged apart from the mechanism extraction verified above.
- [LIMITATION] Live browser E2E was NOT run: these hooks require real microphone capture + a live `AudioContext`, which cannot be meaningfully exercised headlessly (Playwright cannot feed real RMS audio through `getFloatTimeDomainData`). Full manual re-test of Mode 1 dictation, Mode 2 conversation, and barge-in on real hardware is recommended as a pre-deploy smoke check, but the refactor is behaviorally equivalent at the code level.

### Edge Cases Status

#### EC-1: AudioContext creation failure (browser policy) — PASS
- [x] `new AudioContext()` is wrapped in `try/catch` + `console.warn` in both callers (Mode 1 L287, Mode 2 L364), unchanged. The shared hook's `createAnalyser`/`createMediaStreamSource` are not additionally wrapped — neither were they in the original. Equivalent.

#### EC-2: Fast start/stop toggling — no leaked intervals/AudioContexts — PASS
- [x] `stop()` clears the interval and disconnects the source before callers close the AudioContext; Mode 1's `connectingRef` re-entrancy guard is untouched. Cleanup ordering identical to pre-refactor.

#### EC-3: Suspended AudioContext (Mode 2 only) — PASS
- [x] Resume branch runs only when `resumeOnSuspend` is true (Mode 2). On a resume tick, `onSample` is skipped — matching the original's early `return` after `resume()`. Mode 1 is unaffected.

#### EC-4: Browser without AudioContext support — PASS
- [x] Falls through the callers' existing `try/catch` fallback (toast + `cleanup()`), unchanged.

### Security Audit Results

**Client-side audio refactor — red-team review:**
- [x] No new endpoints, routes, or WebSocket message types introduced (grep-confirmed; wire protocol untouched).
- [x] No new data handling: the hook reads local mic RMS only; nothing is transmitted, stored, or logged by `useSilenceDetector`.
- [x] No new external/user input reaches the hook — `onSample` is an internal callback; `start` receives an app-created `MediaStream`/`AudioContext`.
- [x] JWT/token handling untouched (remains in the callers' WS-open paths).
- [x] No injection / auth-bypass / data-leak surface added.
- **Verdict:** No new attack surface. PASS.

### Bugs Found
None in PROJ-69.

#### Observation (NOT a PROJ-69 bug): transient build failure in `src/services/dms.ts`
- **Severity:** N/A to PROJ-69 (environmental / parallel-work artifact)
- The first `npm run build` failed with `Cannot find name 'authHeaders'` in `src/services/dms.ts:87`. On inspection, the current `dms.ts` correctly uses `fetchWithAuth` (no `authHeaders` anywhere in `src/`), and a re-run of `npm run build` passed cleanly. This was `dms.ts` caught mid-edit by a concurrent PROJ-67 (central-auth-fetch-wrapper) session on the same `feature/PROJ-6x-new-frontend-design` branch. It does not involve any PROJ-69 file and does not block PROJ-69. Flagged for the PROJ-67 owner.

### Testing Limitations
- No unit/integration test infrastructure exists in `frontend/` (no `vitest`/`jest`/`@testing-library`/`playwright` in `package.json`; no `*.test.*`/`*.spec.*` files). No automated regression tests could be run for these hooks; verification relied on static behavioral-equivalence diff analysis + type-checking. This is stated rather than fabricated.
- Live microphone / AudioContext browser E2E not performed (see AC-6 limitation).

### Summary
- **Acceptance Criteria:** 6/6 passed (AC-6 by code-equivalence; live manual E2E deferred to pre-deploy smoke).
- **Edge Cases:** 4/4 passed.
- **Bugs Found:** 0 (PROJ-69). 1 unrelated transient build observation in `dms.ts` (PROJ-67).
- **Security:** Pass — no new attack surface.
- **Build:** Pass — `tsc --noEmit` 0 errors, `next build` succeeds.
- **Production Ready:** YES
- **Recommendation:** READY. Refactor is behaviorally equivalent to pre-refactor code. Recommend a quick real-hardware smoke test of Mode 1 dictation, Mode 2 conversation, and barge-in before/after deploy (standard for mic-dependent code that can't be covered headlessly).

## Deployment
_To be added by /deploy_
