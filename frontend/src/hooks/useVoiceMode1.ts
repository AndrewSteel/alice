"use client";

/**
 * useVoiceMode1 — toggle-based push-to-talk that streams a single
 * MediaRecorder blob to `/api/speech/ws/stt` and pushes the returned
 * transcript into the caller via `onTranscript`. No auto-send.
 *
 * Protocol (from PROJ-40 ws_transport.py):
 *  - Client opens WS with `?token=<jwt>`.
 *  - Client sends ONE binary frame containing the whole webm/opus clip.
 *  - Server responds with `{"type":"transcript","text":"..."}` or
 *    `{"type":"error","message":"..."}` and the client closes.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";
import { getToken } from "@/services/auth";

import { useAudioPermission } from "./useAudioPermission";

const WS_URL_BASE = "/api/speech/ws/stt";

function buildWsUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${WS_URL_BASE}?token=${encodeURIComponent(token)}`;
}

interface UseVoiceMode1Options {
  onTranscript: (text: string) => void;
  /** Mode 2 has priority — when true, this hook is fully inert. */
  disabled?: boolean;
}

interface UseVoiceMode1Result {
  isRecording: boolean;
  permissionDenied: boolean;
  toggle: () => void;
}

export function useVoiceMode1({
  onTranscript,
  disabled = false,
}: UseVoiceMode1Options): UseVoiceMode1Result {
  const { toast } = useToast();
  const { permissionDenied, requestStream } = useAudioPermission();

  const [isRecording, setIsRecording] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const recordStartAtRef = useRef<number>(0);

  // Must match MIN_AUDIO_SECONDS in the gateway config.
  const MIN_RECORDING_MS = 500;

  const cleanup = useCallback(() => {
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

    chunksRef.current = [];
    setIsRecording(false);
  }, []);

  // Release resources if the component unmounts mid-recording.
  useEffect(() => cleanup, [cleanup]);

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

    const stream = await requestStream();
    if (!stream) return;
    streamRef.current = stream;

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
    chunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      });
      chunksRef.current = [];

      // Stop the mic immediately — we still hold the WebSocket until the
      // transcript arrives.
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      recorderRef.current = null;

      if (blob.size === 0) {
        cleanup();
        return;
      }

      const durationMs = performance.now() - recordStartAtRef.current;
      if (durationMs < MIN_RECORDING_MS) {
        toast({ title: "Aufnahme zu kurz — bitte nochmals versuchen" });
        cleanup();
        return;
      }

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
        cleanup();
        return;
      }
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = async () => {
        try {
          const buf = await blob.arrayBuffer();
          ws.send(buf);
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("WS send failed", err);
          cleanup();
        }
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "transcript") {
            const text: string = (msg.text ?? "").trim();
            if (text.length > 0) {
              onTranscript(text);
            } else {
              toast({ title: "Nichts verstanden, bitte nochmals versuchen" });
            }
          } else if (msg.type === "error") {
            toast({
              title: "Spracherkennung fehlgeschlagen",
              description: msg.message,
              variant: "destructive",
            });
          }
        } catch {
          /* ignore non-JSON */
        }
        // One transcript per session — close out.
        cleanup();
      };

      ws.onerror = () => {
        toast({
          title: "Sprachverbindung fehlgeschlagen",
          variant: "destructive",
        });
        cleanup();
      };

      ws.onclose = (event) => {
        if (event.code === 4401) {
          toast({
            title: "Sitzung abgelaufen, bitte neu einloggen",
            variant: "destructive",
          });
        }
        // onmessage already cleaned up on success; this guards aborts.
        if (wsRef.current === ws) cleanup();
      };
    };

    try {
      recordStartAtRef.current = performance.now();
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("MediaRecorder.start failed", err);
      cleanup();
    }
  }, [cleanup, onTranscript, requestStream, toast]);

  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        cleanup();
      }
    } else {
      cleanup();
    }
  }, [cleanup]);

  const toggle = useCallback(() => {
    if (disabled || permissionDenied) return;
    if (isRecording) {
      stopRecording();
    } else {
      void startRecording();
    }
  }, [disabled, isRecording, permissionDenied, startRecording, stopRecording]);

  return { isRecording, permissionDenied, toggle };
}
