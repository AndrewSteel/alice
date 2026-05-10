"use client";

import { cn } from "@/lib/utils";
import { Message } from "../types";

interface ThinkingMessageProps {
  message: Message;
}

/**
 * Reserviert für Backend-Thinking-Events (kein aktives Mapping bisher).
 * Visuell: 14px / gray-400, im Textstrom; während Streaming optional Cursor.
 */
export function ThinkingMessage({ message }: ThinkingMessageProps) {
  const { content, streaming } = message;

  return (
    <div className="px-4 py-1.5">
      <div
        className={cn(
          "text-[14px] text-gray-400 italic whitespace-pre-wrap break-words",
          streaming &&
            "after:content-[''] after:inline-block after:w-[2px] after:h-[1em] after:bg-gray-400 after:ml-0.5 after:align-text-bottom after:animate-pulse"
        )}
      >
        {content}
      </div>
    </div>
  );
}
