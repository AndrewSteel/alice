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
const SILENCE_THRESHOLD = 0.015;
const SILENCE_HANG_MS = 1200;
const SILENCE_CHECK_INTERVAL_MS = 100;

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

  // Silence detection
  const analyserRef = useRef<AnalyserNode | null>(null);
  const analyserSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const silenceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );
  const lastVoiceAtRef = useRef<number>(0);
  const utteranceHasVoiceRef = useRef<boolean>(false);

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
      const buffer = ctx.createBuffer(1, samples, TTS_SAMPLE_RATE);
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

    const buf = new Float32Array(analyser.fftSize);
    utteranceHasVoiceRef.current = false;
    lastVoiceAtRef.current = performance.now();

    silenceIntervalRef.current = setInterval(() => {
      if (!analyserRef.current) return;
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
        lastVoiceAtRef.current = now;
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
              case "stt_complete":
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
