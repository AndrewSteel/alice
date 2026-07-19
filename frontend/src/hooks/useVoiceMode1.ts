"use client";

/**
 * useVoiceMode1 — Extended Mode 1 (PROJ-41): streaming push-to-talk with
 * live transcription.
 *
 * The WebSocket opens on button press; MediaRecorder chunks (250 ms) are
 * streamed as binary frames to `/api/speech/ws/stt`. A client-side
 * AnalyserNode watches the mic and, after ~900 ms of silence following
 * detected speech, sends `{type:"end_of_utterance"}` to flush the gateway.
 *
 * Wire protocol (Tech Design — Mode 1 Extended):
 *  - Client → Gateway: WS open (?token=<jwt>), then binary 250 ms chunks.
 *  - Gateway → Client: {"type":"interim","text":"..."}  rolling updates.
 *  - Client → Gateway: {"type":"end_of_utterance"}  on silence / manual stop.
 *  - Gateway → Client: {"type":"final","text":"..."}  then closes the socket.
 *
 * The transcript is pushed into the caller via `onTranscript` (no auto-send).
 * Interim/final updates are blocked once the user manually edits the textarea
 * (`notifyUserEdit`) so we never overwrite their changes.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";
import { getToken } from "@/services/auth";

import { useAudioPermission } from "./useAudioPermission";
import { SILENCE_THRESHOLD, useSilenceDetector } from "./useSilenceDetector";

const WS_URL_BASE = "/api/speech/ws/stt";

// Stream ~every 250 ms so the gateway can build interim transcripts.
const RECORD_TIMESLICE_MS = 250;
// Client-side silence detection (SILENCE_THRESHOLD is defined in the shared
// useSilenceDetector hook). Two hang thresholds:
//   SILENCE_HANG_AFTER_SPEECH_MS — after speech was heard, 900 ms trailing
//     silence triggers auto-stop (original responsive behaviour).
//   SILENCE_HANG_NO_SPEECH_MS   — if no speech is ever detected (mic gain
//     too low to cross the threshold), auto-stop fires 1 500 ms after the
//     button was pressed, so the button can never get permanently stuck.
const SILENCE_HANG_AFTER_SPEECH_MS = 900;
const SILENCE_HANG_NO_SPEECH_MS = 1500;
const SILENCE_CHECK_INTERVAL_MS = 50;

function buildWsUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${WS_URL_BASE}?token=${encodeURIComponent(token)}`;
}

interface UseVoiceMode1Options {
  /** Replace the textarea content with the (composed) transcript. */
  onTranscript: (text: string) => void;
  /** Current textarea text — snapshotted when recording starts. */
  getBaseText: () => string;
  /** Mode 2 has priority — when true, this hook is fully inert. */
  disabled?: boolean;
}

interface UseVoiceMode1Result {
  isRecording: boolean;
  permissionDenied: boolean;
  toggle: () => void;
  /** Call when the user types in the textarea — blocks interim/final injection. */
  notifyUserEdit: () => void;
}

export function useVoiceMode1({
  onTranscript,
  getBaseText,
  disabled = false,
}: UseVoiceMode1Options): UseVoiceMode1Result {
  const { toast } = useToast();
  const { permissionDenied, requestStream } = useAudioPermission();

  const [isRecording, setIsRecording] = useState(false);

  // Latest option closures, mirrored into refs so the long-lived WS and
  // silence-detector callbacks never read a stale textarea snapshot.
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const getBaseTextRef = useRef(getBaseText);
  getBaseTextRef.current = getBaseText;

  // Session resources
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  // BUG-7: blocks a second toggle() tap while the WS is still opening.
  const connectingRef = useRef<boolean>(false);

  // Silence detection (mechanism lives in useSilenceDetector; these track the
  // mode-specific speech state used by the per-tick decision below).
  const lastVoiceAtRef = useRef<number>(0);
  const speechDetectedRef = useRef<boolean>(false);

  // Transcript composition + edit mutex
  const baseTextRef = useRef<string>("");
  const userHasEditedRef = useRef<boolean>(false);
  const endRequestedRef = useRef<boolean>(false);

  // Lets the silence detector call the finalizer without a cyclic dep.
  const finalizeRef = useRef<() => void>(() => {});

  const composeText = useCallback((text: string) => {
    const base = baseTextRef.current.trim();
    return base.length > 0 ? `${base} ${text}` : text;
  }, []);

  // ----- silence detector -----

  // Per-tick decision (mode-specific): auto-stop after the appropriate hang.
  const handleSilenceSample = useCallback((rms: number, now: number) => {
    if (rms > SILENCE_THRESHOLD) {
      lastVoiceAtRef.current = now;
      speechDetectedRef.current = true;
    }

    // Auto-stop: use the shorter post-speech hang when speech has been
    // heard, otherwise fall back to the longer no-speech hang so the
    // button can't get permanently stuck on low-gain devices.
    const hang = speechDetectedRef.current
      ? SILENCE_HANG_AFTER_SPEECH_MS
      : SILENCE_HANG_NO_SPEECH_MS;
    if (now - lastVoiceAtRef.current > hang) {
      finalizeRef.current();
    }
  }, []);

  const { start: startSilenceDetectorRaw, stop: stopSilenceDetector } =
    useSilenceDetector({
      checkIntervalMs: SILENCE_CHECK_INTERVAL_MS,
      onSample: handleSilenceSample,
    });

  const startSilenceDetector = useCallback(
    (stream: MediaStream) => {
      const ctx = audioCtxRef.current;
      if (!ctx) return;
      speechDetectedRef.current = false;
      lastVoiceAtRef.current = performance.now();
      startSilenceDetectorRaw(stream, ctx);
    },
    [startSilenceDetectorRaw],
  );

  // ----- teardown -----

  const cleanup = useCallback(() => {
    stopSilenceDetector();

    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      try {
        recorderRef.current.stop();
      } catch {
        /* already stopped */
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

    baseTextRef.current = "";
    userHasEditedRef.current = false;
    endRequestedRef.current = false;
    speechDetectedRef.current = false;
    connectingRef.current = false;
    setIsRecording(false);
  }, [stopSilenceDetector]);

  // Release resources if the component unmounts mid-recording.
  useEffect(() => cleanup, [cleanup]);

  /**
   * End the current utterance: stop the recorder first so MediaRecorder can
   * emit its final `ondataavailable` chunk, then send `end_of_utterance` in
   * the `onstop` callback. This ensures the gateway never finalises before
   * the last audio chunk arrives (BUG-8). Used by both the silence detector
   * and a manual second click. Idempotent via `endRequestedRef`.
   */
  const finalizeUtterance = useCallback(() => {
    if (endRequestedRef.current) return;
    endRequestedRef.current = true;

    stopSilenceDetector();

    const ws = wsRef.current;
    const recorder = recorderRef.current;
    recorderRef.current = null; // prevent cleanup() from stopping it again

    const sendEouAndCleanupAudio = () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: "end_of_utterance" }));
        } catch {
          /* ignore */
        }
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      if (audioCtxRef.current) {
        const ctx = audioCtxRef.current;
        audioCtxRef.current = null;
        ctx.close().catch(() => {});
      }
    };

    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = sendEouAndCleanupAudio;
      try {
        recorder.stop();
      } catch {
        // recorder threw despite state check — onstop won't fire; flush now
        sendEouAndCleanupAudio();
      }
    } else {
      sendEouAndCleanupAudio();
    }
  }, [stopSilenceDetector]);

  finalizeRef.current = finalizeUtterance;

  // ----- session start -----

  const startRecording = useCallback(async () => {
    const token = getToken();
    if (!token) {
      toast({
        title: "Nicht angemeldet",
        description: "Bitte erneut einloggen.",
        variant: "destructive",
      });
      return;
    }

    connectingRef.current = true;

    const stream = await requestStream();
    if (!stream) {
      connectingRef.current = false;
      return;
    }
    streamRef.current = stream;

    // Reset per-session state and snapshot whatever is already in the
    // textarea so a new dictation is appended, not lost.
    baseTextRef.current = getBaseTextRef.current();
    userHasEditedRef.current = false;
    endRequestedRef.current = false;
    speechDetectedRef.current = false;

    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWsUrl(token));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("WS construct failed", err);
      toast({ title: "Sprachverbindung fehlgeschlagen", variant: "destructive" });
      cleanup();
      return;
    }
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    try {
      audioCtxRef.current = new AudioContext();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("AudioContext failed", err);
      toast({
        title: "Aufnahme nicht unterstützt",
        description: "Dieser Browser kann keine Sprachaufnahmen erzeugen.",
        variant: "destructive",
      });
      cleanup();
      return;
    }

    ws.onopen = () => {
      connectingRef.current = false; // BUG-7: unlock toggle now that WS is ready
      audioCtxRef.current?.resume();

      let recorder: MediaRecorder;
      try {
        recorder = new MediaRecorder(stream);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("MediaRecorder unsupported", err);
        toast({
          title: "Aufnahme nicht unterstützt",
          description: "Dieser Browser kann keine Sprachaufnahmen erzeugen.",
          variant: "destructive",
        });
        cleanup();
        return;
      }
      recorderRef.current = recorder;

      recorder.ondataavailable = async (e) => {
        if (!e.data || e.data.size === 0) return;
        const sock = wsRef.current;
        if (!sock || sock.readyState !== WebSocket.OPEN) return;
        try {
          const sbuf = await e.data.arrayBuffer();
          sock.send(sbuf);
        } catch {
          /* ignore — socket already torn down */
        }
      };

      try {
        recorder.start(RECORD_TIMESLICE_MS);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("MediaRecorder.start failed", err);
        cleanup();
        return;
      }

      startSilenceDetector(stream);
      setIsRecording(true);
    };

    ws.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "interim") {
          if (userHasEditedRef.current) return;
          const text: string = (msg.text ?? "").trim();
          if (text.length > 0) onTranscriptRef.current(composeText(text));
        } else if (msg.type === "final") {
          const text: string = (msg.text ?? "").trim();
          if (userHasEditedRef.current) {
            toast({ title: "Aufnahme abgeschlossen" });
          } else if (text.length > 0) {
            onTranscriptRef.current(composeText(text));
          } else {
            toast({ title: "Nichts verstanden, bitte nochmals versuchen" });
          }
          cleanup();
        } else if (msg.type === "error") {
          toast({
            title: "Spracherkennung fehlgeschlagen",
            description: msg.message,
            variant: "destructive",
          });
          cleanup();
        }
      } catch {
        /* ignore malformed JSON */
      }
    };

    ws.onerror = () => {
      toast({ title: "Sprachverbindung fehlgeschlagen", variant: "destructive" });
      cleanup();
    };

    ws.onclose = (event) => {
      if (event.code === 4401) {
        toast({
          title: "Sitzung abgelaufen, bitte neu einloggen",
          variant: "destructive",
        });
      }
      // `cleanup` nulls wsRef after a successful final; this guards aborts.
      if (wsRef.current === ws) cleanup();
    };
  }, [cleanup, composeText, requestStream, startSilenceDetector, toast]);

  const toggle = useCallback(() => {
    if (disabled || permissionDenied || connectingRef.current) return;
    if (isRecording) {
      finalizeUtterance();
    } else {
      void startRecording();
    }
  }, [disabled, finalizeUtterance, isRecording, permissionDenied, startRecording]);

  const notifyUserEdit = useCallback(() => {
    userHasEditedRef.current = true;
  }, []);

  return { isRecording, permissionDenied, toggle, notifyUserEdit };
}
