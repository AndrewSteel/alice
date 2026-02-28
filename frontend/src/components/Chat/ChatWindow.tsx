"use client";

import { MessageList } from "./MessageList";
import { ChatInputArea } from "./ChatInputArea";

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
}

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  onSend: (text: string) => void;
}

export function ChatWindow({ messages, isLoading, onSend }: ChatWindowProps) {
  return (
    <div className="flex flex-col h-full bg-gray-800">
      <MessageList messages={messages} isLoading={isLoading} />
      <ChatInputArea onSend={onSend} disabled={isLoading} />
    </div>
  );
}
