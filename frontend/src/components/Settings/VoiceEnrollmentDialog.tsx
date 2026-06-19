"use client";

import { useState } from "react";
import { Mic, Square, Check, RotateCcw } from "lucide-react";
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
        setError("Aufnahme war zu kurz oder leer. Bitte erneut versuchen.");
      }
    } else {
      const ok = await start();
      if (!ok) setError("Mikrofon konnte nicht gestartet werden.");
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
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 max-w-md">
        <DialogHeader>
          <DialogTitle>Stimmregistrierung</DialogTitle>
          <DialogDescription className="text-gray-400">
            Nimm {REQUIRED_SAMPLES} kurze Sprachproben auf (je ca. 3 Sekunden).
            Sprich jeweils einen normalen Satz, damit Alice deine Stimme sicher
            erkennt.
          </DialogDescription>
        </DialogHeader>

        {done ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-900/40">
              <Check className="h-6 w-6 text-emerald-400" />
            </div>
            <p className="text-sm text-gray-200">
              Stimmregistrierung abgeschlossen. Alice erkennt dich jetzt an
              deiner Stimme.
            </p>
          </div>
        ) : (
          <div className="space-y-5 py-2">
            {/* Progress */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">Aufgenommene Proben</span>
                <span className="text-gray-200 tabular-nums">
                  {collected}/{REQUIRED_SAMPLES}
                </span>
              </div>
              <Progress
                value={(Math.min(collected, REQUIRED_SAMPLES) / REQUIRED_SAMPLES) * 100}
                className="h-2 bg-gray-700"
              />
              <div className="flex gap-1.5">
                {Array.from({ length: REQUIRED_SAMPLES }).map((_, i) => (
                  <div
                    key={i}
                    className={`h-1.5 flex-1 rounded-full ${
                      i < collected ? "bg-blue-500" : "bg-gray-700"
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
                  aria-label={isRecording ? "Aufnahme stoppen" : "Aufnahme starten"}
                >
                  {isRecording ? (
                    <Square className="h-5 w-5" />
                  ) : (
                    <Mic className="h-6 w-6" />
                  )}
                </Button>
                <p className="text-xs text-gray-400">
                  {isRecording
                    ? "Sprich jetzt … zum Beenden tippen"
                    : `Probe ${collected + 1} aufnehmen`}
                </p>
              </div>
            )}

            {permissionDenied && (
              <p className="text-xs text-red-400 text-center">
                Mikrofonzugriff verweigert. Bitte im Browser erlauben und die
                Seite neu laden.
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
              Fertig
            </Button>
          ) : (
            <>
              {collected > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={handleRedo}
                  disabled={isRecording || isUploading}
                  className="text-gray-300 hover:bg-gray-700 hover:text-gray-100 gap-2"
                >
                  <RotateCcw className="h-4 w-4" />
                  Neu beginnen
                </Button>
              )}
              <Button
                type="button"
                onClick={handleUpload}
                disabled={!complete || isRecording || isUploading}
                className="bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
              >
                {isUploading ? "Wird hochgeladen..." : "Speichern"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
