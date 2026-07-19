"use client";

/**
 * useSilenceDetector — shared client-side RMS silence detection (PROJ-69).
 *
 * Extracted from the near-identical AnalyserNode logic in useVoiceMode1
 * (push-to-talk) and useVoiceMode2 (full-duplex). This hook owns only the
 * detection *mechanism*:
 *  - AnalyserNode setup from a MediaStream on a caller-owned AudioContext,
 *  - RMS calculation via getFloatTimeDomainData,
 *  - interval-based polling,
 *  - cleanup (interval clear + analyser disconnect).
 *
 * What silence *means* stays with the caller: each tick invokes `onSample`
 * with the current linear RMS and a `performance.now()` timestamp. Mode 1
 * uses this to auto-stop; Mode 2 uses it to send `end_of_utterance`.
 *
 * The AudioContext is not owned here — both callers create and close it
 * themselves (Mode 1 for the WS gesture path, Mode 2 for TTS playback), so
 * it is passed into `start`.
 */

import { useCallback, useRef } from "react";

// Client-side silence threshold: -40 dBFS ≈ 0.010 linear RMS. Defined once
// here; both voice modes compare their samples against this.
export const SILENCE_THRESHOLD = 0.01;

interface UseSilenceDetectorOptions {
  /** Polling interval in ms (Mode 1: 50, Mode 2: 100). */
  checkIntervalMs: number;
  /**
   * Called every tick with the current linear RMS and a performance.now()
   * timestamp. The caller decides what silence means (auto-stop vs.
   * end_of_utterance); compare `rms` against SILENCE_THRESHOLD.
   */
  onSample: (rms: number, now: number) => void;
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

        onSampleRef.current(rms, performance.now());
      }, checkIntervalMs);
    },
    [checkIntervalMs, resumeOnSuspend],
  );

  return { start, stop };
}
