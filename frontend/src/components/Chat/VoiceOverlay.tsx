"use client";

import { Square } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

import type { VoiceMode2Status } from "@/hooks/useVoiceMode2";

interface VoiceOverlayProps {
  open: boolean;
  status: VoiceMode2Status;
  onStop: () => void;
}

const STATUS_LABEL_KEY: Record<VoiceMode2Status, string | null> = {
  idle: null,
  connecting: "chat.voiceOverlay.connecting",
  listening: "chat.voiceOverlay.listening",
  processing: "chat.voiceOverlay.processing",
  speaking: "chat.voiceOverlay.speaking",
  ended: "chat.voiceOverlay.ended",
};

const RING_COLOR: Record<VoiceMode2Status, string> = {
  idle: "bg-muted-foreground",
  connecting: "bg-muted-foreground",
  listening: "bg-emerald-500",
  processing: "bg-amber-500",
  speaking: "bg-blue-500",
  ended: "bg-muted-foreground",
};

/**
 * VoiceOverlay — full-screen-ish modal that shows the current voice
 * conversation state. Pure presentational; all session logic lives in
 * `useVoiceMode2`. Closed by user clicking Stop or by the gateway sending
 * `session_ended` (handled in the hook).
 */
export function VoiceOverlay({ open, status, onStop }: VoiceOverlayProps) {
  const { t } = useTranslation();
  const statusKey = STATUS_LABEL_KEY[status];
  // The Dialog reports an onOpenChange when the user presses Escape or
  // clicks the X — route both to the stop handler so the session is torn
  // down cleanly.
  const handleOpenChange = (next: boolean) => {
    if (!next) onStop();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-sm border-border bg-background text-foreground sm:max-w-md"
        aria-describedby={undefined}
      >
        <DialogTitle className="sr-only">{t("chat.voiceOverlay.title")}</DialogTitle>
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
            {statusKey ? t(statusKey) : ""}
          </p>

          <Button
            type="button"
            onClick={onStop}
            variant="destructive"
            className="gap-2"
            aria-label={t("chat.voiceOverlay.stopAria")}
          >
            <Square className="h-4 w-4" fill="currentColor" />
            {t("chat.voiceOverlay.stop")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
