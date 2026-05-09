"use client";

import { MessageList } from "./MessageList";
import { ChatInputArea } from "./ChatInputArea";
import { ActiveTool } from "./ToolStatusChip";

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
}

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
  isStreaming?: boolean;
  activeTools?: ActiveTool[];
  onSend: (text: string) => void;
  onStop?: () => void;
}

export function ChatWindow({
  messages,
  isLoading,
  messagesLoading,
  isStreaming = false,
  activeTools = [],
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
        activeTools={activeTools}
      />
      <ChatInputArea
        onSend={onSend}
        disabled={isLoading || !!messagesLoading}
        isStreaming={isStreaming}
        onStop={onStop}
      />
    </div>
  );
}
