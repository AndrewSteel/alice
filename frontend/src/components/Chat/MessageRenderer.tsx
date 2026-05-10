"use client";

import { Message } from "./types";
import { AssistantMessage } from "./renderers/AssistantMessage";
import { UserMessage } from "./renderers/UserMessage";
import { ToolCallMessage } from "./renderers/ToolCallMessage";
import { ThinkingMessage } from "./renderers/ThinkingMessage";
import { ErrorMessage } from "./renderers/ErrorMessage";
import { StatusMessage } from "./renderers/StatusMessage";

interface MessageRendererProps {
  message: Message;
}

/**
 * Thin dispatcher. New roles only need an entry here and a new renderer file —
 * existing renderers stay untouched.
 */
export function MessageRenderer({ message }: MessageRendererProps) {
  switch (message.role) {
    case "user":
      return <UserMessage message={message} />;
    case "assistant":
      return <AssistantMessage message={message} />;
    case "tool_call":
      return <ToolCallMessage message={message} />;
    case "thinking":
      return <ThinkingMessage message={message} />;
    case "error":
      return <ErrorMessage message={message} />;
    case "status":
      return <StatusMessage message={message} />;
    default: {
      // Exhaustiveness check — TypeScript will error if a new role is added
      // without a renderer entry.
      const _exhaustive: never = message.role;
      return null;
    }
  }
}
