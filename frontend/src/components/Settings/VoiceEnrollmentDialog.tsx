"use client";

import { useState } from "react";
import { Mic, Square, Check, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { useWavRecorder } from "@/hooks/useWavRecorder";
import { enrollVoice } from "@/services/voiceApi";

const REQUIRED_SAMPLES = 5;

interface VoiceEnrollmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful upload so the caller can refresh state. */
  onEnrolled?: () => void;
}

export function VoiceEnrollmentDialog({
  open,
  onOpenChange,
  onEnrolled,
}: VoiceEnrollmentDialogProps) {
  const { t } = useTranslation();
  const { isRecording, permissionDenied, start, stop, cancel } = useWavRecorder();
  const [samples, setSamples] = useState<Blob[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const collected = samples.length;
  const complete = collected >= REQUIRED_SAMPLES;

  function resetState() {
    cancel();
    setSamples([]);
    setError(null);
    setIsUploading(false);
    setDone(false);
  }

  function handleOpenChange(next: boolean) {
    if (isUploading) return; // don't close mid-upload
    if (!next) resetState();
    onOpenChange(next);
  }

  async function handleToggleRecord() {
    setError(null);
    if (isRecording) {
      const blob = await stop();
      if (blob) {
        setSamples((prev) => [...prev, blob]);
      } else {
        setError(t("settings.voiceEnroll.tooShort"));
      }
    } else {
      const ok = await start();
      if (!ok) setError(t("settings.voiceEnroll.micError"));
    }
  }

  function handleRedo() {
    cancel();
    setSamples([]);
    setError(null);
  }

  async function handleUpload() {
    setError(null);
    setIsUploading(true);
    try {
      await enrollVoice(samples.slice(0, REQUIRED_SAMPLES));
      setDone(true);
      onEnrolled?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.unknownError"));
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-card border-border text-foreground max-w-md">
        <DialogHeader>
          <DialogTitle>{t("settings.voiceEnroll.title")}</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {t("settings.voiceEnroll.desc", { count: REQUIRED_SAMPLES })}
          </DialogDescription>
        </DialogHeader>

        {done ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-900/40">
              <Check className="h-6 w-6 text-emerald-400" />
            </div>
            <p className="text-sm text-foreground">
              {t("settings.voiceEnroll.doneMsg")}
            </p>
          </div>
        ) : (
          <div className="space-y-5 py-2">
            {/* Progress */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t("settings.voiceEnroll.recordedSamples")}</span>
                <span className="text-foreground tabular-nums">
                  {collected}/{REQUIRED_SAMPLES}
                </span>
              </div>
              <Progress
                value={(Math.min(collected, REQUIRED_SAMPLES) / REQUIRED_SAMPLES) * 100}
                className="h-2 bg-muted"
              />
              <div className="flex gap-1.5">
                {Array.from({ length: REQUIRED_SAMPLES }).map((_, i) => (
                  <div
                    key={i}
                    className={`h-1.5 flex-1 rounded-full ${
                      i < collected ? "bg-blue-500" : "bg-muted"
                    }`}
                  />
                ))}
              </div>
            </div>

            {/* Record control */}
            {!complete && (
              <div className="flex flex-col items-center gap-2">
                <Button
                  type="button"
                  onClick={handleToggleRecord}
                  disabled={permissionDenied || isUploading}
                  className={`h-14 w-14 rounded-full p-0 ${
                    isRecording
                      ? "bg-red-600 hover:bg-red-700 animate-pulse"
                      : "bg-blue-600 hover:bg-blue-500"
                  } text-white disabled:opacity-50`}
                  aria-label={isRecording ? t("settings.voiceEnroll.recordStop") : t("settings.voiceEnroll.recordStart")}
                >
                  {isRecording ? (
                    <Square className="h-5 w-5" />
                  ) : (
                    <Mic className="h-6 w-6" />
                  )}
                </Button>
                <p className="text-xs text-muted-foreground">
                  {isRecording
                    ? t("settings.voiceEnroll.speakNow")
                    : t("settings.voiceEnroll.recordSample", { n: collected + 1 })}
                </p>
              </div>
            )}

            {permissionDenied && (
              <p className="text-xs text-red-400 text-center">
                {t("settings.voiceEnroll.permissionDenied")}
              </p>
            )}

            {error && (
              <p role="alert" className="text-sm text-red-400 text-center">
                {error}
              </p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          {done ? (
            <Button
              type="button"
              onClick={() => handleOpenChange(false)}
              className="bg-blue-600 hover:bg-blue-500 text-white"
            >
              {t("settings.voiceEnroll.done")}
            </Button>
          ) : (
            <>
              {collected > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={handleRedo}
                  disabled={isRecording || isUploading}
                  className="text-foreground hover:bg-accent hover:text-foreground gap-2"
                >
                  <RotateCcw className="h-4 w-4" />
                  {t("settings.voiceEnroll.restart")}
                </Button>
              )}
              <Button
                type="button"
                onClick={handleUpload}
                disabled={!complete || isRecording || isUploading}
                className="bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
              >
                {isUploading ? t("settings.voiceEnroll.uploading") : t("common.save")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
