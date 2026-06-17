"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines, Mic, Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useVoiceMode1 } from "@/hooks/useVoiceMode1";
import { useVoiceMode2 } from "@/hooks/useVoiceMode2";
import { VoiceOverlay } from "./VoiceOverlay";

// ~6 lines @ ~24px line-height + vertical padding
const MAX_TEXTAREA_HEIGHT_PX = 168;

interface InputAreaProps {
  onSend: (text: string, source?: string) => void;
  disabled: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
}

export function InputArea({
  onSend,
  disabled,
  isStreaming = false,
  onStop,
}: InputAreaProps) {
  const [value, setValue] = useState("");
  const [stopping, setStopping] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wasVoiceInputRef = useRef(false);

  // --- Voice modes ---

  const voice2 = useVoiceMode2();

  // Mode 1 streams interim transcripts: each update replaces the dictated
  // text (rolling replacement). The hook composes base + transcript, so this
  // is a straight replacement, not an append.
  const handleVoiceText = useCallback((text: string) => {
    wasVoiceInputRef.current = true;
    setValue(text);
    // Re-grow the textarea on the next paint.
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX) + "px";
      el.focus();
    });
  }, []);

  const voice1 = useVoiceMode1({
    onTranscript: handleVoiceText,
    // Snapshotted when recording starts so a new dictation is appended.
    getBaseText: () => value,
    // Mode 2 has priority — disable Mode 1 while overlay is active.
    disabled: voice2.isActive,
  });

  const canSend =
    value.trim().length > 0 && !disabled && !isStreaming && !voice1.isRecording;

  // Restore focus after streaming ends or loading completes.
  useEffect(() => {
    if (!isStreaming && !disabled) {
      textareaRef.current?.focus();
    }
  }, [isStreaming, disabled]);

  // Reset transient stopping flag once the stream has actually ended.
  useEffect(() => {
    if (!isStreaming) setStopping(false);
  }, [isStreaming]);

  const handleStop = useCallback(() => {
    if (stopping) return;
    setStopping(true);
    onStop?.();
  }, [onStop, stopping]);

  const handleSend = useCallback(() => {
    if (!canSend) return;
    onSend(value, wasVoiceInputRef.current ? "webapp_mic" : "webapp_cc");
    wasVoiceInputRef.current = false;
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [canSend, onSend, value]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Enter sends, Shift+Enter inserts newline. Enter during streaming is ignored.
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (isStreaming) return;
        handleSend();
      }
    },
    [handleSend, isStreaming],
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      // A manual edit blocks further interim/final injection from Mode 1.
      voice1.notifyUserEdit();
      wasVoiceInputRef.current = false;
      setValue(e.target.value);
      const el = e.target;
      el.style.height = "auto";
      el.style.height =
        Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX) + "px";
    },
    [voice1.notifyUserEdit],
  );

  // --- Voice button derived states ---

  // Mode 1 mic button: disabled while disabled/streaming, while Mode 2
  // overlay is open, or after a permission denial. The denial-after-deny
  // state is fully terminal: re-prompting without a page reload won't
  // re-show the browser dialog.
  const micDisabled =
    disabled || isStreaming || voice2.isActive || voice1.permissionDenied;

  // Mode 2 audio button: disabled while a Mode 1 recording is in flight
  // or after a permission denial.
  const voiceDisabled =
    disabled || isStreaming || voice1.isRecording || voice2.permissionDenied;

  return (
    <>
      <div className="bg-gray-800 px-4 pb-4 pt-2">
        <div className="mx-auto flex w-full max-w-[760px] items-end gap-2">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming ? "Alice antwortet..." : "Nachricht eingeben..."
            }
            disabled={disabled || isStreaming}
            rows={1}
            style={{ maxHeight: MAX_TEXTAREA_HEIGHT_PX }}
            className="flex-1 resize-none bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-400 focus-visible:ring-gray-500 min-h-[44px] overflow-y-auto"
            aria-label="Nachricht eingeben"
          />

          {/* Mode 1 — Mikrofon */}
          <Button
            type="button"
            onClick={voice1.toggle}
            disabled={micDisabled}
            size="icon"
            variant="ghost"
            className={
              voice1.isRecording
                ? "h-[44px] w-[44px] shrink-0 bg-red-600 text-white hover:bg-red-700 relative animate-pulse"
                : "h-[44px] w-[44px] shrink-0 bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:bg-gray-700 disabled:text-gray-500"
            }
            aria-label={
              voice1.isRecording
                ? "Aufnahme beenden und transkribieren"
                : "Spracheingabe starten"
            }
            aria-pressed={voice1.isRecording}
          >
            {voice1.isRecording && (
              <span
                className="absolute inset-0 rounded-md ring-2 ring-red-400 animate-ping"
                aria-hidden
              />
            )}
            <Mic className="h-4 w-4 relative" />
          </Button>

          {/* Mode 2 — Full Voice */}
          <Button
            type="button"
            onClick={() => void voice2.start()}
            disabled={voiceDisabled}
            size="icon"
            variant="ghost"
            className="h-[44px] w-[44px] shrink-0 bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:bg-gray-700 disabled:text-gray-500"
            aria-label="Sprachgespräch starten"
          >
            <AudioLines className="h-4 w-4" />
          </Button>

          {/* Send / Stop */}
          {isStreaming ? (
            <Button
              type="button"
              onClick={handleStop}
              disabled={stopping}
              size="icon"
              variant="destructive"
              className="h-[44px] w-[44px] shrink-0 disabled:opacity-60"
              aria-label="Antwort abbrechen"
            >
              <Square className="h-4 w-4" fill="currentColor" />
            </Button>
          ) : (
            <Button
              onClick={handleSend}
              disabled={!canSend}
              size="icon"
              className="h-[44px] w-[44px] shrink-0 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:text-gray-400"
              aria-label="Nachricht senden"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      <VoiceOverlay
        open={voice2.isActive}
        status={voice2.status}
        onStop={voice2.stop}
      />
    </>
  );
}
