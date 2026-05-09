"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";
import { ToolStatusChip, ActiveTool } from "./ToolStatusChip";
import { MessageSquare, Loader2 } from "lucide-react";
import { MessageSegment } from "@/hooks/useChatSessions";

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  segments?: MessageSegment[];
  timestamp: Date;
}

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
  /** True while a streaming response is being received (PROJ-31). */
  isStreaming?: boolean;
  /** Currently active tools for the in-flight stream. */
  activeTools?: ActiveTool[];
}

export function MessageList({
  messages,
  isLoading,
  messagesLoading,
  isStreaming = false,
  activeTools = [],
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);
  const prevMessageCount = useRef(0);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      userScrolledUp.current = scrollTop + clientHeight < scrollHeight - 100;
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const lengthChanged = messages.length !== prevMessageCount.current;
    prevMessageCount.current = messages.length;
    if (lengthChanged || !isStreaming) {
      userScrolledUp.current = false;
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    } else if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isLoading, isStreaming]);

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

  if (messages.length === 0 && !isLoading && !isStreaming) {
    return (
      <div className="flex flex-1 items-center justify-center h-full">
        <div className="text-center space-y-3">
          <MessageSquare className="h-10 w-10 text-gray-500 mx-auto" />
          <p className="text-gray-400 text-base">Wie kann ich helfen?</p>
        </div>
      </div>
    );
  }

  // Identify the last assistant message -- it's the one currently streaming.
  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIdx = i;
      break;
    }
  }

  // Show the typing indicator when waiting for the first token (no assistant
  // bubble yet OR the bubble is empty), but suppress it once tokens arrive
  // or a tool is running (ToolStatusChip takes over the "working" signal).
  const lastAssistantContent =
    lastAssistantIdx >= 0 ? messages[lastAssistantIdx].content : "";
  const showTypingIndicator =
    (isLoading && !isStreaming) ||
    (isStreaming && lastAssistantContent.length === 0 && activeTools.length === 0);

  return (
    <div ref={scrollContainerRef} className="flex flex-col flex-1 overflow-y-auto py-4" role="log" aria-label="Chatverlauf">
      {messages.map((msg, i) => {
        // Don't render the empty streaming placeholder — TypingIndicator covers this state.
        if (isStreaming && i === lastAssistantIdx && msg.content === "") return null;
        return (
          <MessageBubble
            key={i}
            role={msg.role}
            content={msg.content}
            segments={msg.segments}
            streaming={isStreaming && i === lastAssistantIdx}
          />
        );
      })}
      {isStreaming && activeTools.length > 0 && (
        <ToolStatusChip tools={activeTools} />
      )}
      {showTypingIndicator && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  );
}
