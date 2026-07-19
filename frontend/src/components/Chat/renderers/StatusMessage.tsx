"use client";

import { Message } from "../types";

interface StatusMessageProps {
  message: Message;
}

export function StatusMessage({ message }: StatusMessageProps) {
  return (
    <div className="px-4 py-1">
      <p className="text-[13px] text-muted-foreground italic">{message.content}</p>
    </div>
  );
}
