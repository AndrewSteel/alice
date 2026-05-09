"use client";

import { Loader2 } from "lucide-react";

/**
 * Tool-name → user-facing status label.
 * Matches the tool names emitted by alice-chat-stream (PROJ-30).
 */
const TOOL_LABELS: Record<string, string> = {
  search_documents: "Suche in Dokumenten...",
  get_document_details: "Lade Dokument...",
  home_assistant: "Steuere Gerät...",
  remember: "Merke mir...",
  recall: "Erinnere mich...",
};

const TOOL_ICONS: Record<string, string> = {
  search_documents: "🔍",
  get_document_details: "📄",
  home_assistant: "💡",
  remember: "🧠",
  recall: "🧠",
};

export interface ActiveTool {
  /** Tool name as emitted by the backend (e.g. "search_documents"). */
  tool: string;
  /** Optional backend-provided status text; falls back to TOOL_LABELS. */
  status?: string;
}

interface ToolStatusChipProps {
  tools: ActiveTool[];
}

export function ToolStatusChip({ tools }: ToolStatusChipProps) {
  if (tools.length === 0) return null;

  return (
    <div
      className="flex flex-wrap gap-2 px-4 pb-2"
      aria-live="polite"
      aria-label="Aktive Tools"
    >
      {tools.map(({ tool, status }) => {
        const label = status || TOOL_LABELS[tool] || `${tool}...`;
        const icon = TOOL_ICONS[tool];
        return (
          <div
            key={tool}
            className="inline-flex items-center gap-2 rounded-full bg-gray-700/80 border border-gray-600 px-3 py-1.5 text-xs text-gray-200"
          >
            {icon ? (
              <span aria-hidden="true">{icon}</span>
            ) : (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            )}
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
}
