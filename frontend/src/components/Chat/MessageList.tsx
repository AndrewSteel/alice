"use client";

import { useEffect, useRef, useCallback } from "react";
import { MessageSquare, Loader2 } from "lucide-react";
import { MessageRenderer } from "./MessageRenderer";
import { TypingIndicator } from "./TypingIndicator";
import { Message } from "./types";

const NEAR_BOTTOM_PX = 150;

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  messagesLoading?: boolean;
  isStreaming?: boolean;
}

export function MessageList({
  messages,
  isLoading,
  messagesLoading,
  isStreaming = false,
}: MessageListProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const prevCount = useRef(0);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  }, []);

  // Auto-scroll contract:
  //  - Always scroll when a new message is appended (count grew). Token-append
  //    during streaming mutates content without changing the array length, so
  //    countChanged precisely captures "a new message began" — even when two
  //    messages are added in the same render burst (user + assistant placeholder).
  //  - During streaming token-append: only scroll when user is within
  //    NEAR_BOTTOM_PX of the bottom.
  //  - After stream end: do NOT force scroll.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const countChanged = messages.length !== prevCount.current;

    prevCount.current = messages.length;

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    const nearBottom = distanceFromBottom <= NEAR_BOTTOM_PX;

    if (countChanged) {
      scrollToBottom();
      return;
    }

    if (isStreaming && nearBottom) {
      scrollToBottom();
    }
  }, [messages, isStreaming, scrollToBottom]);

  if (messagesLoading) {
    return (
      <div className="flex flex-1 items-center justify-center h-full">
        <div className="text-center space-y-3">
          <Loader2 className="h-8 w-8 text-muted-foreground mx-auto animate-spin" />
          <p className="text-muted-foreground text-sm">Nachrichten werden geladen...</p>
        </div>
      </div>
    );
  }

  if (messages.length === 0 && !isLoading && !isStreaming) {
    return (
      <div className="flex flex-1 items-center justify-center h-full">
        <div className="text-center space-y-3">
          <MessageSquare className="h-10 w-10 text-muted-foreground mx-auto" />
          <p className="text-muted-foreground text-base">Wie kann ich helfen?</p>
        </div>
      </div>
    );
  }

  // Show typing indicator until the first token of an assistant/thinking
  // message arrives or a tool_call message is emitted.
  const lastMsg = messages[messages.length - 1];
  const lastIsEmptyAssistant =
    !!lastMsg &&
    (lastMsg.role === "assistant" || lastMsg.role === "thinking") &&
    lastMsg.content.length === 0;
  const showTypingIndicator =
    (isLoading && !isStreaming) || (isStreaming && lastIsEmptyAssistant);

  return (
    <div
      ref={scrollContainerRef}
      className="flex-1 min-h-0 overflow-y-auto"
      role="log"
      aria-label="Chatverlauf"
    >
      <div className="mx-auto w-full max-w-[760px] py-4">
        {messages.map((msg) => {
          // Suppress empty streaming placeholder — TypingIndicator covers it.
          if (
            isStreaming &&
            (msg.role === "assistant" || msg.role === "thinking") &&
            msg.content.length === 0
          ) {
            return null;
          }
          return <MessageRenderer key={msg.id} message={msg} />;
        })}
        {showTypingIndicator && <TypingIndicator />}
      </div>
    </div>
  );
}
