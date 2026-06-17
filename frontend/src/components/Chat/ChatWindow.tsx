"use client";

import { MessageList } from "./MessageList";
import { InputArea } from "./InputArea";
import { Message } from "./types";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
  isStreaming?: boolean;
  onSend: (text: string, source?: string) => void;
  onStop?: () => void;
}

export function ChatWindow({
  messages,
  isLoading,
  messagesLoading,
  isStreaming = false,
  onSend,
  onStop,
}: ChatWindowProps) {
  return (
    <div className="flex flex-col h-full bg-gray-800">
      <MessageList
        messages={messages}
        isLoading={isLoading}
        messagesLoading={messagesLoading}
        isStreaming={isStreaming}
      />
      <InputArea
        onSend={onSend}
        disabled={isLoading || !!messagesLoading}
        isStreaming={isStreaming}
        onStop={onStop}
      />
    </div>
  );
}
