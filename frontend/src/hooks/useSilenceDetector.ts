"use client";

/**
 * useSilenceDetector — shared client-side RMS silence detection (PROJ-69),
 * with an adaptive noise-floor calibration phase (PROJ-70).
 *
 * Extracted from the near-identical AnalyserNode logic in useVoiceMode1
 * (push-to-talk) and useVoiceMode2 (full-duplex). This hook owns only the
 * detection *mechanism*:
 *  - AnalyserNode setup from a MediaStream on a caller-owned AudioContext,
 *  - RMS calculation via getFloatTimeDomainData,
 *  - interval-based polling,
 *  - a short per-recording calibration window that measures the ambient
 *    noise floor and derives the active speech threshold (PROJ-70),
 *  - cleanup (interval clear + analyser disconnect).
 *
 * What silence *means* stays with the caller: after calibration, each tick
 * invokes `onSample` with the current linear RMS, a `performance.now()`
 * timestamp, and the *effective* threshold this recording should compare
 * against. Mode 1 uses this to auto-stop; Mode 2 uses it to send
 * `end_of_utterance`. Callers must compare `rms` against the passed
 * `threshold`, not a fixed constant.
 *
 * Adaptive calibration (PROJ-70): unlike the ESPHome device (PROJ-57) which
 * estimates the noise floor continuously while idle, the browser only powers
 * the mic once a recording starts. So the first CALIBRATION_WINDOW_MS of each
 * recording are spent measuring ambient RMS as a baseline (no `onSample`
 * during this window). The active threshold is then frozen for the rest of
 * the recording at `noise_floor × NOISE_MARGIN_FACTOR`, clamped so it can
 * only ever *raise* the bar above today's fixed SILENCE_THRESHOLD — never
 * lower it (non-regression guarantee: a quiet room behaves byte-identically
 * to before PROJ-70). Both modes share this strategy verbatim; each recording
 * (and, in Mode 2, each turn's `start`) calibrates independently.
 *
 * The AudioContext is not owned here — both callers create and close it
 * themselves (Mode 1 for the WS gesture path, Mode 2 for TTS playback), so
 * it is passed into `start`.
 */

import { useCallback, useRef } from "react";

// Client-side silence threshold: -40 dBFS ≈ 0.010 linear RMS. Defined once
// here; it is the *floor* for the adaptive threshold — the calibrated
// threshold can raise the bar above this but never below it.
export const SILENCE_THRESHOLD = 0.01;

// PROJ-70 calibration heuristics (shared by both modes — no mode-specific
// tuning). Both are field-tunable without a new spec cycle.
//
//  CALIBRATION_WINDOW_MS — length of the ambient-noise measurement window at
//    the start of each recording. 400 ms is long enough to average several
//    RMS samples on both cadences (Mode 1 @ 50 ms → ~8 samples, Mode 2 @
//    100 ms → ~4 samples) yet short enough to stay imperceptible before the
//    user speaks.
//  NOISE_MARGIN_FACTOR — the active threshold sits this far above the
//    measured noise floor. Mirrors PROJ-57's ESPHome value (1.8) so the two
//    implementations of the same principle stay aligned.
//  MIN_CALIBRATION_SAMPLES — need at least this many samples to trust the
//    mean; otherwise fall back to the fixed SILENCE_THRESHOLD (covers a
//    recording shorter than the calibration window, or a mid-window resume).
const CALIBRATION_WINDOW_MS = 400;
const NOISE_MARGIN_FACTOR = 1.8;
const MIN_CALIBRATION_SAMPLES = 2;

interface UseSilenceDetectorOptions {
  /** Polling interval in ms (Mode 1: 50, Mode 2: 100). */
  checkIntervalMs: number;
  /**
   * Called every tick *after* the calibration window with the current linear
   * RMS, a performance.now() timestamp, and the effective (frozen) threshold
   * this recording calibrated to. The caller decides what silence means
   * (auto-stop vs. end_of_utterance); compare `rms` against `threshold`, not
   * a fixed constant. Not called during the calibration window.
   */
  onSample: (rms: number, now: number, threshold: number) => void;
  /**
   * Mode 2 only: resume a suspended AudioContext during polling (Chrome may
   * auto-suspend between turns). On the tick that resumes, `onSample` is not
   * called. Mode 1 leaves this off.
   */
  resumeOnSuspend?: boolean;
}

interface SilenceDetector {
  /** Wire an AnalyserNode onto `stream` via `ctx` and begin polling. */
  start: (stream: MediaStream, ctx: AudioContext) => void;
  /** Clear the interval and disconnect the analyser graph. */
  stop: () => void;
}

export function useSilenceDetector({
  checkIntervalMs,
  onSample,
  resumeOnSuspend = false,
}: UseSilenceDetectorOptions): SilenceDetector {
  // Mirror the latest callback into a ref so the long-lived interval never
  // reads a stale closure.
  const onSampleRef = useRef(onSample);
  onSampleRef.current = onSample;

  const analyserRef = useRef<AnalyserNode | null>(null);
  const analyserSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // PROJ-70 calibration state (reset in `start`, per recording/turn).
  const calibratingRef = useRef<boolean>(false);
  const calibStartRef = useRef<number>(0);
  const calibSumRef = useRef<number>(0);
  const calibCountRef = useRef<number>(0);
  // Effective threshold for the current recording. Starts at the fixed floor
  // and is frozen to the calibrated value once the window elapses.
  const thresholdRef = useRef<number>(SILENCE_THRESHOLD);

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (analyserSourceRef.current) {
      try {
        analyserSourceRef.current.disconnect();
      } catch {
        /* ignore */
      }
      analyserSourceRef.current = null;
    }
    analyserRef.current = null;
    ctxRef.current = null;
  }, []);

  const start = useCallback(
    (stream: MediaStream, ctx: AudioContext) => {
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      const source = ctx.createMediaStreamSource(stream);
      source.connect(analyser);
      analyserRef.current = analyser;
      analyserSourceRef.current = source;
      ctxRef.current = ctx;

      // Begin a fresh calibration window for this recording/turn. Until it
      // closes, ticks feed the noise-floor estimate and `onSample` is
      // suppressed; the threshold defaults to the fixed floor as a fallback.
      calibratingRef.current = true;
      calibStartRef.current = performance.now();
      calibSumRef.current = 0;
      calibCountRef.current = 0;
      thresholdRef.current = SILENCE_THRESHOLD;

      // Connect the analyser into the graph at gain 0 so browsers that only
      // process nodes wired to the destination still deliver audio data. The
      // mic is never audible through the speakers.
      const silentGain = ctx.createGain();
      silentGain.gain.value = 0;
      analyser.connect(silentGain);
      silentGain.connect(ctx.destination);

      const buf = new Float32Array(analyser.fftSize);

      intervalRef.current = setInterval(() => {
        const analyserNode = analyserRef.current;
        const activeCtx = ctxRef.current;
        if (!analyserNode || !activeCtx) return;

        // Resume if Chrome auto-suspended the context between turns.
        if (resumeOnSuspend && activeCtx.state === "suspended") {
          activeCtx.resume();
          return;
        }

        analyserNode.getFloatTimeDomainData(buf);
        let sumSq = 0;
        for (let i = 0; i < buf.length; i++) sumSq += buf[i] * buf[i];
        const rms = Math.sqrt(sumSq / buf.length);
        const now = performance.now();

        // Calibration phase: accumulate ambient RMS, don't run the caller's
        // decision yet. When the window elapses, freeze the threshold at
        // noise_floor × margin, clamped so it can only exceed the fixed floor.
        if (calibratingRef.current) {
          calibSumRef.current += rms;
          calibCountRef.current += 1;
          if (now - calibStartRef.current >= CALIBRATION_WINDOW_MS) {
            if (calibCountRef.current >= MIN_CALIBRATION_SAMPLES) {
              const noiseFloor = calibSumRef.current / calibCountRef.current;
              thresholdRef.current = Math.max(
                SILENCE_THRESHOLD,
                noiseFloor * NOISE_MARGIN_FACTOR,
              );
            } else {
              // Too few samples to trust — keep the fixed fallback.
              thresholdRef.current = SILENCE_THRESHOLD;
            }
            calibratingRef.current = false;
          }
          return;
        }

        onSampleRef.current(rms, now, thresholdRef.current);
      }, checkIntervalMs);
    },
    [checkIntervalMs, resumeOnSuspend],
  );

  return { start, stop };
}
