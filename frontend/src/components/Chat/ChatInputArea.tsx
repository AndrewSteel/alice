"use client";

import { useCallback, useRef, useState } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputAreaProps {
  onSend: (text: string) => void;
  disabled: boolean;
  /** True while a streaming response is in flight (PROJ-31). */
  isStreaming?: boolean;
  /** Called when the user clicks the Stop button during a stream. */
  onStop?: () => void;
}

export function ChatInputArea({
  onSend,
  disabled,
  isStreaming = false,
  onStop,
}: ChatInputAreaProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = value.trim().length > 0 && !disabled && !isStreaming;

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
      // Enter during streaming must NOT trigger a new request (AC).
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
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    },
    []
  );

  return (
    <div className="bg-gray-800 px-4 pb-4 pt-2">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={isStreaming ? "Alice antwortet..." : "Nachricht eingeben..."}
          disabled={disabled || isStreaming}
          rows={1}
          className="flex-1 resize-none bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-400 focus-visible:ring-gray-500 min-h-[44px] max-h-[200px]"
          aria-label="Nachricht eingeben"
        />
        {isStreaming ? (
          <Button
            type="button"
            onClick={onStop}
            size="icon"
            variant="destructive"
            className="h-[44px] w-[44px] shrink-0"
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
