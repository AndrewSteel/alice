"use client";

import { AlertCircle } from "lucide-react";
import { Message } from "../types";

interface ErrorMessageProps {
  message: Message;
}

export function ErrorMessage({ message }: ErrorMessageProps) {
  return (
    <div className="px-4 py-2">
      <div
        role="alert"
        className="flex items-start gap-2 rounded-md border border-red-700/50 bg-red-900/30 px-3 py-2"
      >
        <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" aria-hidden="true" />
        <p className="text-[14px] text-red-300 whitespace-pre-wrap break-words">
          {message.content}
        </p>
      </div>
    </div>
  );
}
