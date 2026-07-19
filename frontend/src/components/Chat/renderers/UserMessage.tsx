"use client";

import { Message } from "../types";

interface UserMessageProps {
  message: Message;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end px-4 py-2">
      <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-[16px] text-foreground">
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
      </div>
    </div>
  );
}
