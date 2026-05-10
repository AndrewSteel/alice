"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// ~6 lines @ ~24px line-height + vertical padding
const MAX_TEXTAREA_HEIGHT_PX = 168;

interface InputAreaProps {
  onSend: (text: string) => void;
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

  const canSend = value.trim().length > 0 && !disabled && !isStreaming;

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
    onSend(value);
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
    [handleSend, isStreaming]
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setValue(e.target.value);
      const el = e.target;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX) + "px";
    },
    []
  );

  return (
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
  );
}
