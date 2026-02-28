"use client";

import { useCallback, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputAreaProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function ChatInputArea({ onSend, disabled }: ChatInputAreaProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = value.trim().length > 0 && !disabled;

  const handleSend = useCallback(() => {
    if (!canSend) return;
    onSend(value);
    setValue("");
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [canSend, onSend, value]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setValue(e.target.value);
      // Auto-resize textarea
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
          placeholder="Nachricht eingeben..."
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-400 focus-visible:ring-gray-500 min-h-[44px] max-h-[200px]"
          aria-label="Nachricht eingeben"
        />
        <Button
          onClick={handleSend}
          disabled={!canSend}
          size="icon"
          className="h-[44px] w-[44px] shrink-0 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:text-gray-400"
          aria-label="Nachricht senden"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
