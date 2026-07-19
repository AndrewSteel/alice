# PROJ-70: Browser-Sprachmodi — Adaptiver Noise-Floor

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- `useSilenceDetector.ts` extended with a 400ms calibration window, `NOISE_MARGIN_FACTOR = 1.8` (mirrors PROJ-57's ESPHome-side constant), `MIN_CALIBRATION_SAMPLES = 2`. Effective threshold = `Math.max(SILENCE_THRESHOLD, noiseFloor × margin)`, frozen after calibration for the rest of the recording.
- `onSample` signature extended to `(rms, now, threshold)`; both voice-mode hooks compare against the passed threshold instead of the fixed constant.
- QA: READY, 0 bugs. Live-microphone tuning smoke test (Chrome + Safari, quiet/noisy room, tap-release, multi-turn Mode 2) recommended pre-deploy — margin factor and window length are field-tunable without a new spec cycle if needed.

## Dependencies
- Requires: PROJ-69 (Voice-Hooks Silence-Detection-Extraktion) — diese Spec erweitert den dort extrahierten gemeinsamen Hook um adaptive Kalibrierung, statt erneut in zwei Dateien zu duplizieren.
- Verwandt: PROJ-57 (On-Device VAD Noise Robustness, Deployed) — gleiches Grundproblem (fester RMS-Schwellwert reagiert schlecht auf Umgebungsgeräusch) für das ESPHome-Gerät bereits gelöst; diese Spec überträgt das Prinzip auf den Browser, mit angepasster Kalibrierungsstrategie (siehe Kontext).
- Explizit **nicht** Teil dieser Spec: Trennung von Nutzer-Stimme und sprachähnlichem Hintergrund (TV/Radio) — das ist PROJ-58, ein separates Quelltrennungsproblem.

## Kontext

Anders als das ESPHome-Gerät (PROJ-57) hat der Browser keine dauerhafte Idle-Hörphase, in der das Mikrofon bereits läuft, bevor eine Aufnahme beginnt — das Mikrofon wird erst beim Start einer Aufnahme (Mode 1) bzw. beim Öffnen des Voice-Overlays (Mode 2) aktiviert. Die Kalibrierung kann daher nicht wie bei PROJ-57 kontinuierlich im Hintergrund vor dem Trigger laufen, sondern nutzt ein kurzes Kalibrierungsfenster zu Beginn jeder Aufnahme.

## User Stories
- Als Nutzer möchte ich Alice per Sprache auch bei laufendem Lüfter, offenem Fenster mit Straßenlärm oder ähnlichem Dauergeräusch nutzen können, ohne dass die Aufnahme unnötig lange auf die feste 900ms-Stille wartet.
- Als Nutzer möchte ich, dass sich in einem leisen Raum nichts am bisherigen, bereits funktionierenden Verhalten ändert.
- Als Nutzer möchte ich keinerlei manuellen Kalibrierschritt durchführen ("bitte kurz still sein") — die Anpassung soll transparent im Hintergrund jeder Aufnahme passieren.

## Acceptance Criteria
- [ ] Der gemeinsame Silence-Detection-Hook (PROJ-69) misst zu Beginn jeder Aufnahme ein kurzes Kalibrierungsfenster (Richtwert 300–500ms, final in `/architecture`) als Ambient-Noise-Baseline, bevor die eigentliche Sprach-/Stille-Erkennung aktiv wird.
- [ ] Der aktive Sprache-Schwellwert wird aus `noise_floor × Margin-Faktor` berechnet und nach unten auf den heutigen Fixwert (`SILENCE_THRESHOLD = 0.01`) begrenzt — in einem leisen Raum bleibt das Verhalten exakt identisch zu heute (keine Regression).
- [ ] Der Schwellwert wird nach dem Kalibrierungsfenster für den Rest der laufenden Aufnahme eingefroren (verhindert, dass die eigene Stimme des Nutzers die Schätzung verfälscht) — analog zu PROJ-57.
- [ ] Beide Modi (Push-to-Talk und Vollduplex) nutzen dieselbe Kalibrierungsstrategie (kurzes Fenster pro Aufnahme/Turn, kein Unterschied zwischen den Modi).
- [ ] Bei einem Dauergeräusch, das über dem heutigen Fixwert liegt (z. B. Lüfter, Straßenlärm), endet die Aufnahme innerhalb der üblichen Stille-Zeitspanne (~900ms) nachdem der Nutzer aufgehört hat zu sprechen — nicht erst durch den Server-seitigen Gateway-Timeout (30s).
- [ ] Kein manueller Kalibrierschritt, keine neue UI — Verhalten ist für den Nutzer transparent.

## Edge Cases
- Nutzer beginnt sofort zu sprechen, ohne Pause vor dem Sprechbeginn (Kalibrierungsfenster erfasst bereits die eigene Stimme statt reinem Umgebungsgeräusch): bekannte Grenze, führt im schlimmsten Fall zu einem zu hohen Schwellwert für diese eine Aufnahme — kein Blocker, analog zur entsprechenden Grenze in PROJ-57.
- Umgebungsgeräusch ändert sich merklich während einer laufenden Aufnahme (z. B. Tür wird geöffnet), nachdem der Schwellwert bereits eingefroren wurde: keine Anpassung innerhalb derselben Aufnahme, wird erst bei der nächsten Aufnahme/dem nächsten Turn berücksichtigt (identisch zu PROJ-57s Design-Entscheidung).
- Sehr kurze Aufnahme (Nutzer tippt Mikrofon-Button an und lässt sofort wieder los, kürzer als das Kalibrierungsfenster): Kalibrierung darf nicht blockieren oder abstürzen — Fallback auf den festen Schwellwert (0.01) bei unzureichenden Samples.
- Extrem lautes/variables Umgebungsgeräusch (z. B. direkt neben einem Staubsauger), bei dem auch der adaptive Schwellwert keine zuverlässige Trennung erlaubt: bestehender Gateway-seitiger 30s-Timeout bleibt das ultimative Sicherheitsnetz — kein Hängenbleiben, keine neue Absicherung nötig, da diese bereits serverseitig existiert.
- Mode 2 (Vollduplex, mehrere Turns pro Sitzung): jeder Turn kalibriert unabhängig neu, kein Zustand wird zwischen Turns übernommen (bewusst einfacher als eine kontinuierliche Zwischen-Turn-Schätzung, siehe Kontext).

## Technical Requirements (optional)
- Änderung erfolgt ausschließlich im gemeinsamen Hook aus PROJ-69 — kein Protokoll-/Gateway-Change, keine neuen WebSocket-Nachrichtentypen.
- Margin-Faktor und Länge des Kalibrierungsfensters sind Heuristik-Werte (analog zu PROJ-57s `NOISE_MARGIN_FACTOR`), final in `/architecture` festgelegt und ohne neuen Spec-Zyklus nachjustierbar.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
useSilenceDetector.ts (aus PROJ-69, erweitert um Kalibrierungsphase — kein neuer Komponenten-Baum)
+-- Kalibrierungsfenster (300–500ms) zu Beginn jeder Aufnahme: sammelt RMS-Samples als Ambient-Noise-Baseline
+-- aktiver Schwellwert = noise_floor × Margin-Faktor, nach unten auf den heutigen Fixwert (0.01) begrenzt
+-- Schwellwert wird nach dem Kalibrierungsfenster für die restliche Aufnahme eingefroren
+-- zu kurze Aufnahme (< Kalibrierungsfenster) → Fallback auf Fixwert 0.01, kein Blockieren/Absturz
```

#### B) Data Model

Keine — der berechnete Schwellwert ist ein rein flüchtiger Wert pro Aufnahme/Turn, wird danach verworfen (explizit kein turnübergreifender Zustand, siehe Kontext-Abschnitt der Spec).

#### C) Tech Decisions

- **Erweitert PROJ-69s Hook statt eines neuen Hooks:** vermeidet erneute Duplizierung der AnalyserNode-/RMS-Plumbing — genau deshalb musste PROJ-69 zuerst landen (bereits als Dependency vermerkt).
- **Kalibrierungsfenster pro Aufnahme statt kontinuierlicher Hintergrund-Kalibrierung wie bei PROJ-57:** Der Browser hat keine dauerhafte Idle-Hörphase (Mikrofon aktiviert erst bei Aufnahmestart) — dieser strukturelle Unterschied zum ESPHome-Gerät schließt PROJ-57s kontinuierlichen Ansatz aus; stattdessen wird dasselbe Grundprinzip (`noise_floor × Margin-Faktor`) auf ein kurzes Fenster zu Beginn jeder Aufnahme übertragen.
- **Nach unten auf den Fixwert begrenzt (0.01):** garantiert keine Verhaltensänderung in einem leisen Raum (explizites Non-Regressions-Kriterium) — der adaptive Schwellwert kann die Schwelle nur anheben, nie unter die heutige Baseline absenken.
- **Beide Sprachmodi teilen sich eine Kalibrierungsstrategie** (kein Mode-spezifisches Tuning) — hält das Modell einfach und erfüllt das Akzeptanzkriterium identischen Verhaltens zwischen Mode 1/2.
- **Margin-Faktor und Fensterlänge sind Heuristik-Werte** (analog zu PROJ-57s `NOISE_MARGIN_FACTOR`) — laut Spec explizit ohne neuen Spec-Zyklus im Feld nachjustierbar; Startwerte werden bei `/frontend`/QA anhand realer Umgebungsgeräusche festgelegt.
- **Kein Protokoll-/Gateway-Change:** Der bestehende serverseitige 30s-Timeout bleibt das Sicherheitsnetz für den Extremfall (sehr lautes/variables Umgebungsgeräusch), diese Spec ändert daran nichts.

#### D) Dependencies

Keine neuen Pakete.

## QA Test Results

**Tested:** 2026-07-19
**Tester:** QA Engineer (AI)
**Scope:** Adaptive noise-floor calibration added to the shared `useSilenceDetector.ts` (PROJ-69) plus the `onSample` signature change consumed by `useVoiceMode1.ts` (push-to-talk) and `useVoiceMode2.ts` (full-duplex). Bar = "adaptive threshold raises the bar under continuous noise, quiet-room behavior unchanged, both modes share one strategy, short recordings never block."
**Method:** Full read of all three hook files (post-PROJ-70), line-by-line calibration-state trace, `git diff HEAD` surgical-change audit, cross-check of the PROJ-57 `NOISE_MARGIN_FACTOR` constant in the actual ESPHome source, `npm run build`, and constructed sample-sequence hand-traces of the state machine. No live microphone (see Testing Limitations).

### Verification Evidence
- PROJ-57 constant claim **verified, not fabricated:** `devices/ha-voice-pe/components/wyoming_satellite/wyoming_satellite.h:134` → `static constexpr float NOISE_MARGIN_FACTOR = 1.8f;` (used at `wyoming_satellite.cpp:263`). The browser `NOISE_MARGIN_FACTOR = 1.8` (useSilenceDetector.ts:62) mirrors it exactly.
- `onSample` genuinely suppressed during calibration: the calibration branch (L181–198) `return`s before ever reaching `onSampleRef.current(...)` at L200 — it is not called with a bogus threshold, it is not called at all during the window.
- Calibration state reset on **every** `start()` (L145–149): `calibratingRef`, `calibStartRef`, `calibSumRef`, `calibCountRef`, and `thresholdRef` are all re-initialized at the top of `start`. No stale-closure/cross-recording carryover — the single most likely defect class for this change is absent. Verified per-turn independence in Mode 2 (each turn calls `startSilenceDetector` → `start`).
- `Math.max(SILENCE_THRESHOLD, noiseFloor * NOISE_MARGIN_FACTOR)` clamp sits exactly where claimed (L187–190), inside the window-elapsed freeze block.
- `onSampleRef` mirror (L98–99) keeps the long-lived interval from reading a stale callback.
- Voice-mode diffs are surgical: only (a) dropped the now-unused `SILENCE_THRESHOLD` import, (b) added the `threshold` param and compare `rms > threshold` instead of `rms > SILENCE_THRESHOLD`, (c) comment updates. The two-stage (Mode 1: 900/1500ms) and one-stage (Mode 2: 900ms + 5s no-speech) hang timing from PROJ-69 is byte-identical (the large line count is pure reindentation from single-line to multi-line arrow callbacks). No dangling `SILENCE_THRESHOLD` reference remains in either caller (grep-confirmed: it now appears only inside `useSilenceDetector.ts`).
- `git diff HEAD` touching gateway/protocol: **none.** Only `frontend/src/hooks/{useSilenceDetector,useVoiceMode1,useVoiceMode2}.ts` for PROJ-70. (`package.json`/`package-lock.json` also show `i18next`/`react-i18next` additions — these are concurrent PROJ-62 i18n work on the shared `feature/PROJ-6x` branch, NOT PROJ-70; PROJ-70 itself adds no package, matching "Keine neuen Pakete.")
- `npm run build`: **PASS** — compiled + type-checked + static export, 0 errors.

### Hand-Traced State Machine
- **Noisy room, 3 calibration samples @ 0.02 RMS:** noiseFloor = 0.06/3 = 0.02 → threshold = max(0.01, 0.02×1.8 = 0.036) = **0.036**. Bar correctly raised above the 0.01 floor — trailing 900ms silence now ends the recording instead of the fan noise pinning `rms > 0.01` forever (the AC-5 failure mode pre-PROJ-70).
- **Quiet room, ambient ~0.002 RMS:** threshold = max(0.01, 0.0036) = **0.01**. Identical to pre-PROJ-70 → non-regression guarantee holds (clamp can only raise, never lower).
- **Mode 1 window (50ms interval, 400ms window):** ~8 samples accumulate before `now - calibStart >= 400` freezes; Mode 2 (100ms) ~4 samples — both ≥ MIN_CALIBRATION_SAMPLES=2.

### Acceptance Criteria Status

#### AC-1: Calibration window measures ambient baseline before active detection — PASS
- [x] `CALIBRATION_WINDOW_MS = 400` (within the spec's 300–500ms range). RMS samples accumulate into `calibSumRef`/`calibCountRef` during the window; `onSample` is not invoked until the window elapses (L181–198 return-before-callback).

#### AC-2: Threshold = noise_floor × margin, clamped up to the fixed 0.01 floor — PASS
- [x] `noiseFloor = calibSum / calibCount`; `threshold = Math.max(0.01, noiseFloor × 1.8)`. Clamp guarantees no downward move → quiet-room byte-identical (hand-trace above).

#### AC-3: Threshold frozen after the window for the rest of the recording — PASS
- [x] `calibratingRef` set `false` once, only re-armed by the next `start()`. After freeze the interval always takes the `onSample` path with the frozen `thresholdRef.current`. No mid-recording recalibration — matches PROJ-57's design.

#### AC-4: Both modes use the identical calibration strategy (no mode-specific constants) — PASS
- [x] All three heuristics (`CALIBRATION_WINDOW_MS`, `NOISE_MARGIN_FACTOR`, `MIN_CALIBRATION_SAMPLES`) live once in `useSilenceDetector.ts`. Neither caller defines or overrides any calibration constant; both simply consume the passed `threshold`.

#### AC-5: Continuous noise above 0.01 ends recording within ~900ms of silence, not via the 30s gateway timeout — PASS (by code/trace; live-mic deferred)
- [x] With ambient noise raising the threshold above the fan/street RMS, the standard hang timers (Mode 1: 900ms post-speech; Mode 2: 900ms EOU) fire normally. Pre-PROJ-70 the fixed 0.01 would keep registering the noise as "speech," deferring stop to the server 30s timeout.

#### AC-6: No manual calibration step, no new UI — PASS
- [x] Calibration runs transparently inside `start()`. Zero UI/JSX changes in the diff; no user-facing prompt.

### Edge Cases Status

#### EC-1: User speaks immediately (no pre-speech pause) — PASS (graceful degradation)
- [x] Calibration averages the user's own voice → an over-high threshold for that one recording. No crash/hang: Mode 1's 1500ms no-speech hang and Mode 2's 5s no-speech session-end still guarantee termination. Matches the spec's accepted limitation (analogous to PROJ-57).

#### EC-2: Noise changes mid-recording after freeze — PASS
- [x] No recalibration within the recording (`calibratingRef` stays `false`); adjustment only on the next recording/turn. Matches the spec's explicit design choice.

#### EC-3: Very short tap-and-release (shorter than the window) — PASS
- [x] If `stop()` fires before the window elapses, the interval is cleared; `onSample` was never called during calibration → nothing blocks or crashes. If the window elapses with `< MIN_CALIBRATION_SAMPLES`, threshold falls back to the fixed 0.01 (L191–193).

#### EC-4: Extreme/variable noise → existing 30s gateway timeout untouched — PASS
- [x] No gateway/protocol/WS files touched (diff-confirmed). The server-side 30s safety net is unchanged and remains the ultimate backstop.

#### EC-5: Mode 2 suspend during calibration window (PROJ-69 resume interaction) — PASS
- [x] The `resumeOnSuspend` early-return (L167–170) runs *before* the calibration branch, so a suspend tick neither samples nor advances the estimate — it defers calibration. If the context is suspended for the whole window and resumes with too few samples, the `MIN_CALIBRATION_SAMPLES` fallback yields the fixed 0.01. Graceful.

### Security Audit Results
**Client-side audio math — red-team review:**
- [x] No new endpoints, routes, or WebSocket message types; wire protocol untouched (diff-confirmed).
- [x] No new data leaves the browser: calibration reads local mic RMS only; nothing transmitted, stored, or logged.
- [x] No new external/user input reaches the hook; `onSample` is an internal callback.
- [x] JWT/token handling untouched (remains in callers' WS-open paths).
- **Verdict:** No new attack surface. **PASS.**

### Bugs Found
None.

#### Observation (NOT a PROJ-70 bug): unrelated dependency additions in `package.json`
- **Severity:** N/A to PROJ-70 (concurrent-work artifact)
- `git diff HEAD` shows `i18next`/`react-i18next` added to `frontend/package.json` + lockfile. These belong to PROJ-62 (frontend-i18n) on the shared `feature/PROJ-6x-new-frontend-design` branch, not PROJ-70. PROJ-70 adds no package (consistent with its "Keine neuen Pakete."). Flagged only so it is not mistaken for PROJ-70 scope. Build still passes with them present.

### Testing Limitations
- No unit/integration test infra in `frontend/` (no vitest/jest/testing-library/playwright). Verification is static behavioral analysis + type-check/build + hand-traced sample sequences.
- Live microphone / AudioContext E2E not performed — `getFloatTimeDomainData` cannot be fed real RMS headlessly. **What cannot be verified without hardware:** the *actual* ambient RMS magnitudes in a real quiet vs. noisy room and whether 1.8× reliably clears real fan/street noise (a tuning question, not a correctness one — the constants are field-tunable per spec).
- **Recommended pre-deploy real-device smoke test (Chrome + Safari):** (1) quiet room — confirm Mode 1 dictation and Mode 2 conversation behave as before; (2) noisy room (fan/open window) — confirm recording ends ~900ms after speech stops, not after 30s; (3) tap-and-release under 400ms — confirm no hang; (4) multi-turn Mode 2 — confirm each turn recalibrates independently.

### Summary
- **Acceptance Criteria:** 6/6 passed (AC-5 by code/trace; live-mic tuning check deferred to smoke test).
- **Edge Cases:** 5/5 passed.
- **Bugs Found:** 0 (1 unrelated concurrent-work observation on `package.json`, PROJ-62).
- **Security:** Pass — no new attack surface.
- **Build:** Pass — `next build` clean, 0 type errors.
- **Production Ready:** YES
- **Recommendation:** **READY.** Implementation matches the spec precisely — calibration suppresses `onSample`, state resets every `start()`, the `Math.max` clamp guarantees non-regression, both modes share one strategy, and short/suspend/extreme-noise paths degrade gracefully into the fixed floor or the existing 30s gateway net. Run the mic smoke test above before/after deploy (standard for mic-dependent code that can't be covered headlessly).

## Deployment
_To be added by /deploy_
