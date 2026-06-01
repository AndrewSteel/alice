"use client";

import { Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

import type { VoiceMode2Status } from "@/hooks/useVoiceMode2";

interface VoiceOverlayProps {
  open: boolean;
  status: VoiceMode2Status;
  onStop: () => void;
}

const STATUS_LABEL: Record<VoiceMode2Status, string> = {
  idle: "",
  connecting: "Verbinde…",
  listening: "Höre zu…",
  processing: "Alice denkt…",
  speaking: "Alice spricht…",
  ended: "Gespräch beendet",
};

const RING_COLOR: Record<VoiceMode2Status, string> = {
  idle: "bg-gray-500",
  connecting: "bg-gray-400",
  listening: "bg-emerald-500",
  processing: "bg-amber-500",
  speaking: "bg-blue-500",
  ended: "bg-gray-500",
};

/**
 * VoiceOverlay — full-screen-ish modal that shows the current voice
 * conversation state. Pure presentational; all session logic lives in
 * `useVoiceMode2`. Closed by user clicking Stop or by the gateway sending
 * `session_ended` (handled in the hook).
 */
export function VoiceOverlay({ open, status, onStop }: VoiceOverlayProps) {
  // The Dialog reports an onOpenChange when the user presses Escape or
  // clicks the X — route both to the stop handler so the session is torn
  // down cleanly.
  const handleOpenChange = (next: boolean) => {
    if (!next) onStop();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-sm border-gray-700 bg-gray-900 text-gray-100 sm:max-w-md"
        aria-describedby={undefined}
      >
        <DialogTitle className="sr-only">Sprachgespräch mit Alice</DialogTitle>
        <div className="flex flex-col items-center gap-8 py-6">
          {/* Animated state ring */}
          <div className="relative flex h-32 w-32 items-center justify-center">
            <span
              className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${RING_COLOR[status]}`}
              aria-hidden
            />
            <span
              className={`relative inline-flex h-20 w-20 rounded-full ${RING_COLOR[status]}`}
              aria-hidden
            />
          </div>

          <p className="text-xl font-medium" aria-live="polite" role="status">
            {STATUS_LABEL[status]}
          </p>

          <Button
            type="button"
            onClick={onStop}
            variant="destructive"
            className="gap-2"
            aria-label="Sprachgespräch beenden"
          >
            <Square className="h-4 w-4" fill="currentColor" />
            Beenden
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
