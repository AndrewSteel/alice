"use client";

import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  role: "user" | "assistant" | "error";
  content: string;
}

export function MessageBubble({ role, content }: MessageBubbleProps) {
  if (role === "error") {
    return (
      <div className="flex items-start gap-3 px-4 py-2">
        <div className="flex items-start gap-2 rounded-2xl bg-red-900/40 border border-red-700/50 px-4 py-3 max-w-[85%] md:max-w-[70%]">
          <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
          <p className="text-sm text-red-300 whitespace-pre-wrap break-words">
            {content}
          </p>
        </div>
      </div>
    );
  }

  const isUser = role === "user";

  return (
    <div
      className={cn(
        "flex px-4 py-2",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] md:max-w-[70%] rounded-2xl px-4 py-3",
          isUser
            ? "bg-gray-600 text-gray-100"
            : "bg-transparent text-gray-200"
        )}
      >
        <p className="text-sm whitespace-pre-wrap break-words">{content}</p>
      </div>
    </div>
  );
}
