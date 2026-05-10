/**
 * Chat message types — single source of truth for the message-stream model.
 *
 * Every visually distinct piece of content in the chat is a `Message` with an
 * explicit `role`. Renderers dispatch on `role`; new roles only require a new
 * renderer file (no changes to existing components).
 */

export type MessageRole =
  | "user" // user input
  | "assistant" // LLM answer text (markdown, full typography)
  | "tool_call" // tool invocation: name + status text, 14px / gray
  | "thinking" // LLM intermediate text / reasoning, 14px / gray
  | "error" // error message, red style
  | "status"; // system info (connection status etc.)

export type ToolStatus = "running" | "done" | "error";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: number; // unix ms
  streaming?: boolean;

  // Only when role === "tool_call":
  toolName?: string;
  toolStatus?: ToolStatus;

  // Reserved extension points (no breaking change to add more later):
  // attachments?: Attachment[]
  // metadata?: Record<string, unknown>
}
