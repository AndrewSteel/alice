"use client";

import { MessageList } from "./MessageList";
import { Message } from "./types";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
  isStreaming?: boolean;
}

export function ChatWindow({
  messages,
  isLoading,
  messagesLoading,
  isStreaming = false,
}: ChatWindowProps) {
  return (
    <div className="flex flex-col h-full bg-card">
      <MessageList
        messages={messages}
        isLoading={isLoading}
        messagesLoading={messagesLoading}
        isStreaming={isStreaming}
      />
    </div>
  );
}
