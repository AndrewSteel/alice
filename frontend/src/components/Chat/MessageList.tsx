"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";
import { MessageSquare, Loader2 } from "lucide-react";

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
}

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
}

export function MessageList({ messages, isLoading, messagesLoading }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages or when loading state changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Messages loading from backend (AC-C2)
  if (messagesLoading) {
    return (
      <div className="flex flex-1 items-center justify-center h-full">
        <div className="text-center space-y-3">
          <Loader2 className="h-8 w-8 text-gray-500 mx-auto animate-spin" />
          <p className="text-gray-400 text-sm">Nachrichten werden geladen...</p>
        </div>
      </div>
    );
  }

  // Empty state for sessions without messages (AC-C10)
  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center h-full">
        <div className="text-center space-y-3">
          <MessageSquare className="h-10 w-10 text-gray-500 mx-auto" />
          <p className="text-gray-400 text-base">Wie kann ich helfen?</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 overflow-y-auto py-4" role="log" aria-label="Chatverlauf">
      {messages.map((msg, i) => (
        <MessageBubble key={i} role={msg.role} content={msg.content} />
      ))}
      {isLoading && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  );
}
