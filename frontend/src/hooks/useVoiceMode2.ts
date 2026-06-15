"use client";

/**
 * useVoiceMode2 — full-voice conversation against `/api/speech/ws/voice`.
 *
 * Wire protocol (PROJ-40):
 *  - Binary frames from server  → raw 16-bit signed PCM mono @ 22050 Hz
 *    (wyoming-piper default; Piper does not transmit sample-rate metadata
 *    on the wire, so we hard-code it here).
 *  - JSON frames from server    → `{type:"session", session_id}` once on
 *    connect, then `{type:"status", status}` events. Status values:
 *      listening        → turn complete, ready for next utterance
 *      stt_complete     → STT done, waiting for AI
 *      ai_processing    → LLM is generating
 *      tts_generating   → TTS audio is being streamed
 *      session_ended    → server closed the session
 *  - Binary frames from client  → MediaRecorder webm/opus chunks.
 *  - JSON frames from client    → `{type:"end_of_utterance"}` to flush a
 *    captured utterance, `{type:"stop"}` to end the session.
 *
 * State machine:
 *   idle → listening → processing → speaking → listening (continued conv.)
 *                                   ↘ ended
 *
 * Barge-in: while `status === "speaking"`, MediaRecorder continues to
 * stream audio. Any new status event during speaking is treated as a
 * server-side interrupt acknowledgement — we flush the playback queue and
 * follow the new status.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";
import { getToken } from "@/services/auth";

import { useAudioPermission } from "./useAudioPermission";

export type VoiceMode2Status =
  | "idle"
  | "connecting"
  | "listening"
  | "processing"
  | "speaking"
  | "ended";

const WS_URL_BASE = "/api/speech/ws/voice";
// Piper's default voice sample rate. The Wyoming AudioChunk events carry
// this in the protocol, but the gateway only forwards `.audio` bytes — so
// the browser must know it out-of-band.
const TTS_SAMPLE_RATE = 22050;
// Push roughly every 250 ms (PROJ-41 tech design) so the gateway can react
// fast to silence/utterance-end.
const RECORD_TIMESLICE_MS = 250;
// Local silence detector: we tell the gateway "end of utterance" after
// this much continuous silence while in `listening`.
const SILENCE_THRESHOLD = 0.010;
const SILENCE_HANG_MS = 900;
const SILENCE_CHECK_INTERVAL_MS = 100;
// If no speech at all is detected for this long while in `listening`, end the
// session. Covers: (1) CC button pressed but user doesn't speak, (2) after TTS
// the user stays silent. Gateway timeout is 30 s — this gives a faster close.
const NO_SPEECH_SESSION_END_MS = 5000;

function buildWsUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${WS_URL_BASE}?token=${encodeURIComponent(token)}`;
}

interface UseVoiceMode2Result {
  status: VoiceMode2Status;
  isActive: boolean;
  permissionDenied: boolean;
  /** Open overlay + start session. */
  start: () => Promise<void>;
  /** Stop session and close overlay. */
  stop: () => void;
}

export function useVoiceMode2(): UseVoiceMode2Result {
  const { toast } = useToast();
  const { permissionDenied, requestStream } = useAudioPermission();

  const [status, setStatus] = useState<VoiceMode2Status>("idle");
  const isActive = status !== "idle" && status !== "ended";

  // Mirror `status` into a ref so async callbacks (WS handlers, silence
  // interval) read the live value instead of a stale closure.
  const statusRef = useRef<VoiceMode2Status>("idle");
  const updateStatus = useCallback((next: VoiceMode2Status) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  // --- refs (all mutable session state) ---
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);

  // Audio playback
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef<AudioBufferSourceNode[]>([]);
  const nextStartTimeRef = useRef<number>(0);
  // BUG-5: actual Piper sample rate sent by the gateway in the first
  // audio_format frame; falls back to the hard-coded default until received.
  const ttsRateRef = useRef<number>(TTS_SAMPLE_RATE);
  // Kept current with the `stop` callback so the silence interval can call it
  // without capturing a stale closure (stopRef itself is stable).
  const stopRef = useRef<() => void>(() => {});

  // Silence detection
  const analyserRef = useRef<AnalyserNode | null>(null);
  const analyserSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const silenceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );
  const lastVoiceAtRef = useRef<number>(0);
  const utteranceHasVoiceRef = useRef<boolean>(false);
  // True between sending end_of_utterance and receiving stt_complete/listening
  // from the gateway — blocks the no-speech auto-close while the pipeline is
  // processing the utterance the user just spoke.
  const utteranceInFlightRef = useRef<boolean>(false);

  // ----- playback helpers -----

  const flushPlayback = useCallback(() => {
    const queue = playbackQueueRef.current;
    queue.forEach((node) => {
      try {
        node.stop();
      } catch {
        /* already stopped */
      }
      try {
        node.disconnect();
      } catch {
        /* ignore */
      }
    });
    playbackQueueRef.current = [];
    nextStartTimeRef.current = 0;
  }, []);

  /** Convert raw 16-bit signed PCM mono into an AudioBuffer. */
  const pcmToAudioBuffer = useCallback(
    (ctx: AudioContext, pcm: ArrayBuffer): AudioBuffer | null => {
      if (pcm.byteLength < 2) return null;
      const samples = pcm.byteLength / 2;
      const view = new DataView(pcm);
      const buffer = ctx.createBuffer(1, samples, ttsRateRef.current);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples; i++) {
        const s = view.getInt16(i * 2, true);
        channel[i] = s / 32768;
      }
      return buffer;
    },
    [],
  );

  const enqueueAudioChunk = useCallback(
    (chunk: ArrayBuffer) => {
      const ctx = audioCtxRef.current;
      if (!ctx) return;
      const buffer = pcmToAudioBuffer(ctx, chunk);
      if (!buffer) return;

      const node = ctx.createBufferSource();
      node.buffer = buffer;
      node.connect(ctx.destination);

      const startAt = Math.max(ctx.currentTime, nextStartTimeRef.current);
      node.start(startAt);
      nextStartTimeRef.current = startAt + buffer.duration;

      playbackQueueRef.current.push(node);
      node.onended = () => {
        const queue = playbackQueueRef.current;
        const idx = queue.indexOf(node);
        if (idx >= 0) queue.splice(idx, 1);
        // When the last chunk finishes playing and the gateway has already
        // signalled `listening`, reset the no-speech timer from NOW so the
        // 5 s window starts after audio output ends, not when `listening`
        // was received (which is before playback finishes).
        if (queue.length === 0 && statusRef.current === "listening") {
          lastVoiceAtRef.current = performance.now();
        }
      };
    },
    [pcmToAudioBuffer],
  );

  // ----- silence detector -----

  const stopSilenceDetector = useCallback(() => {
    if (silenceIntervalRef.current) {
      clearInterval(silenceIntervalRef.current);
      silenceIntervalRef.current = null;
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
  }, []);

  const startSilenceDetector = useCallback((stream: MediaStream) => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    const source = ctx.createMediaStreamSource(stream);
    source.connect(analyser);
    analyserRef.current = analyser;
    analyserSourceRef.current = source;

    // Connect analyser into the processing graph so browsers that only
    // analyse nodes connected to the destination actually deliver audio.
    // Gain = 0 means the mic is never heard through the speakers.
    const silentGain = ctx.createGain();
    silentGain.gain.value = 0;
    analyser.connect(silentGain);
    silentGain.connect(ctx.destination);

    const buf = new Float32Array(analyser.fftSize);
    utteranceHasVoiceRef.current = false;
    utteranceInFlightRef.current = false;
    lastVoiceAtRef.current = performance.now();

    silenceIntervalRef.current = setInterval(() => {
      const silenceCtx = audioCtxRef.current;
      if (!analyserRef.current || !silenceCtx) return;
      // Resume if Chrome auto-suspended the context between turns.
      if (silenceCtx.state === "suspended") {
        silenceCtx.resume();
        return;
      }
      analyserRef.current.getFloatTimeDomainData(buf);
      let sumSq = 0;
      for (let i = 0; i < buf.length; i++) sumSq += buf[i] * buf[i];
      const rms = Math.sqrt(sumSq / buf.length);

      const now = performance.now();
      if (rms > SILENCE_THRESHOLD) {
        lastVoiceAtRef.current = now;
        utteranceHasVoiceRef.current = true;
      }

      // Only flush utterances when we're actually capturing (listening).
      // Capturing during `speaking` is barge-in territory — the gateway
      // owns interrupt detection in that case.
      if (
        statusRef.current === "listening" &&
        utteranceHasVoiceRef.current &&
        now - lastVoiceAtRef.current > SILENCE_HANG_MS
      ) {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "end_of_utterance" }));
        }
        utteranceHasVoiceRef.current = false;
        utteranceInFlightRef.current = true; // block no-speech close until gateway acks
        // lastVoiceAtRef intentionally NOT reset here — the no-speech timer
        // restarts only when the gateway sends `listening` (after TTS).
        return;
      }

      // No speech at all for NO_SPEECH_SESSION_END_MS → end the session.
      // Handles: (1) CC opened but user never speaks, (2) post-TTS silence.
      // Guards:
      //   utteranceInFlight — blocked while gateway processes the utterance
      //   playbackQueue empty — blocked while browser is still playing audio
      //     (gateway sends `listening` before playback finishes; lastVoiceAtRef
      //     is reset in node.onended when the last chunk plays out)
      if (
        statusRef.current === "listening" &&
        !utteranceHasVoiceRef.current &&
        !utteranceInFlightRef.current &&
        playbackQueueRef.current.length === 0 &&
        now - lastVoiceAtRef.current > NO_SPEECH_SESSION_END_MS
      ) {
        stopRef.current();
      }
    }, SILENCE_CHECK_INTERVAL_MS);
  }, []);

  // ----- session teardown -----

  const teardown = useCallback(() => {
    stopSilenceDetector();
    flushPlayback();

    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      try {
        recorderRef.current.stop();
      } catch {
        /* ignore */
      }
    }
    recorderRef.current = null;

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        /* ignore */
      }
      wsRef.current = null;
    }

    if (audioCtxRef.current) {
      const ctx = audioCtxRef.current;
      audioCtxRef.current = null;
      ctx.close().catch(() => {});
    }
  }, [flushPlayback, stopSilenceDetector]);

  // Close everything if the component unmounts or tab is hidden/unloaded.
  useEffect(() => {
    const onUnload = () => teardown();
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      teardown();
    };
  }, [teardown]);

  // ----- public API -----

  const stop = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "stop" }));
      } catch {
        /* ignore */
      }
    }
    teardown();
    updateStatus("idle");
  }, [teardown]);

  // Keep stopRef pointing at the latest stop so the silence interval can call
  // it without a stale closure. Runs on every render (safe — ref mutation).
  stopRef.current = stop;

  const start = useCallback(async () => {
    if (isActive) return;

    const token = getToken();
    if (!token) {
      toast({
        title: "Nicht angemeldet",
        description: "Bitte erneut einloggen.",
        variant: "destructive",
      });
      return;
    }

    updateStatus("connecting");
    ttsRateRef.current = TTS_SAMPLE_RATE; // reset to default until gateway sends audio_format

    const stream = await requestStream();
    if (!stream) {
      updateStatus("idle");
      return;
    }
    streamRef.current = stream;

    // Build the WebSocket first; the gateway expects audio frames after
    // the JWT-validated handshake.
    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWsUrl(token));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("WS construct failed", err);
      toast({
        title: "Sprachverbindung fehlgeschlagen",
        variant: "destructive",
      });
      teardown();
      updateStatus("idle");
      return;
    }
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    // AudioContext on a user-gesture path (start was triggered by a click).
    try {
      audioCtxRef.current = new AudioContext();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("AudioContext failed", err);
      toast({
        title: "Audioausgabe nicht verfügbar",
        variant: "destructive",
      });
      teardown();
      updateStatus("idle");
      return;
    }

    ws.onopen = () => {
      // Ensure AudioContext is running — Chrome may defer activation even
      // when created from a user gesture if no audio has played yet.
      audioCtxRef.current?.resume();

      // Start capturing as soon as the socket is up.
      let recorder: MediaRecorder;
      try {
        recorder = new MediaRecorder(stream);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("MediaRecorder unsupported", err);
        toast({
          title: "Aufnahme nicht unterstützt",
          variant: "destructive",
        });
        teardown();
        updateStatus("idle");
        return;
      }
      recorderRef.current = recorder;

      recorder.ondataavailable = async (e) => {
        if (!e.data || e.data.size === 0) return;
        const sock = wsRef.current;
        if (!sock || sock.readyState !== WebSocket.OPEN) return;
        try {
          const buf = await e.data.arrayBuffer();
          sock.send(buf);
        } catch {
          /* ignore — socket already torn down */
        }
      };

      try {
        recorder.start(RECORD_TIMESLICE_MS);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("MediaRecorder.start failed", err);
        teardown();
        updateStatus("idle");
        return;
      }
      startSilenceDetector(stream);
      updateStatus("listening");
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "status") {
            switch (msg.status) {
              case "listening":
                // Server finished the turn (TTS done) — transition back to
                // listening. Reset the silence detector so:
                //   - the no-speech timer starts from TTS completion, not
                //     from when the user last spoke
                //   - a spurious immediate EOU can't fire from a stale flag
                utteranceInFlightRef.current = false;
                utteranceHasVoiceRef.current = false;
                lastVoiceAtRef.current = performance.now(); // no-speech timer starts here
                updateStatus("listening");
                break;
              case "stt_complete":
                utteranceInFlightRef.current = false; // gateway acked the utterance
                // If we were speaking, this is a barge-in ack: flush
                // playback immediately so the user hears the new answer
                // cleanly.
                if (statusRef.current === "speaking") flushPlayback();
                updateStatus("processing");
                break;
              case "ai_processing":
                updateStatus("processing");
                break;
              case "tts_generating":
                updateStatus("speaking");
                break;
              case "session_ended":
                teardown();
                updateStatus("idle");
                break;
            }
          } else if (msg.type === "audio_format") {
            // BUG-5: use the actual Piper sample rate instead of hard-coding 22050.
            if (typeof msg.rate === "number" && msg.rate > 0) {
              ttsRateRef.current = msg.rate;
            }
          } else if (msg.type === "session") {
            // session_id is logged on the server; nothing to render.
          } else if (msg.type === "error") {
            toast({
              title: "Sprachfehler",
              description: msg.message,
              variant: "destructive",
            });
          }
        } catch {
          /* ignore malformed JSON */
        }
        return;
      }
      // Binary frame → TTS audio chunk
      if (event.data instanceof ArrayBuffer) {
        enqueueAudioChunk(event.data);
      }
    };

    ws.onerror = () => {
      toast({
        title: "Sprachverbindung fehlgeschlagen",
        variant: "destructive",
      });
      teardown();
      updateStatus("idle");
    };

    ws.onclose = (event) => {
      if (event.code === 4401) {
        toast({
          title: "Sitzung abgelaufen, bitte neu einloggen",
          variant: "destructive",
        });
      }
      // Silence-timeout closes (code 1000) just end the overlay.
      teardown();
      updateStatus("idle");
    };
  }, [
    enqueueAudioChunk,
    flushPlayback,
    isActive,
    requestStream,
    startSilenceDetector,
    teardown,
    toast,
    updateStatus,
  ]);

  return { status, isActive, permissionDenied, start, stop };
}
