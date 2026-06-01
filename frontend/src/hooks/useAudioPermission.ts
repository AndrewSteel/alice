"use client";

/**
 * useAudioPermission — shared microphone permission helper for the two
 * voice modes (PROJ-41). It exposes a single `requestStream()` call that
 * returns a live `MediaStream` on success and surfaces a German toast on
 * denial. Once the user denies access (or the browser has no microphone)
 * we set `permissionDenied = true`; callers should disable their entry
 * buttons in that state — re-prompting without a page reload is pointless
 * because the browser will not re-show the permission dialog.
 */

import { useCallback, useState } from "react";

import { useToast } from "@/hooks/use-toast";

const AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

interface UseAudioPermissionResult {
  /** True after a denial — callers should disable their buttons. */
  permissionDenied: boolean;
  /** Acquire a fresh MediaStream or return null on failure. */
  requestStream: () => Promise<MediaStream | null>;
}

export function useAudioPermission(): UseAudioPermissionResult {
  const { toast } = useToast();
  const [permissionDenied, setPermissionDenied] = useState(false);

  const requestStream = useCallback(async (): Promise<MediaStream | null> => {
    if (permissionDenied) return null;
    if (typeof navigator === "undefined" || !navigator.mediaDevices) {
      setPermissionDenied(true);
      toast({
        title: "Mikrofon nicht verfügbar",
        description: "Dieser Browser unterstützt keine Mikrofonaufnahme.",
        variant: "destructive",
      });
      return null;
    }
    try {
      return await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
    } catch (err) {
      setPermissionDenied(true);
      toast({
        title: "Mikrofonzugriff verweigert",
        description:
          "Bitte in den Browser-Einstellungen erlauben und Seite neu laden.",
        variant: "destructive",
      });
      // Surface the underlying cause for debugging without breaking on Safari
      // where `err` may not be a DOMException.
      // eslint-disable-next-line no-console
      console.warn("getUserMedia failed", err);
      return null;
    }
  }, [permissionDenied, toast]);

  return { permissionDenied, requestStream };
}
