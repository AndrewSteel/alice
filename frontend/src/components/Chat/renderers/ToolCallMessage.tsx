"use client";

import { Loader2, Check, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Message } from "../types";

interface ToolCallMessageProps {
  message: Message;
}

/**
 * Tool calls render as a dezent, kompakter Fließtext-Block (14px / gray-400).
 * Backend liefert beschreibenden `content` (z.B. "Suche in Dokumenten…"),
 * Fallback ist der `toolName`. Status-Icon: Spinner / Haken / Warnung.
 */
export function ToolCallMessage({ message }: ToolCallMessageProps) {
  const { t } = useTranslation();
  const { content, toolName, toolStatus } = message;
  const label = content || toolName || t("chat.tool.runningFallback");
  // Default to a running spinner if status is missing (defensive: e.g. malformed
  // SSE payload or a future session-restore path that omits the field).
  const effectiveStatus = toolStatus ?? "running";

  return (
    <div className="px-4 py-1.5">
      <div
        className={cn(
          "flex items-center gap-2 text-[14px] text-muted-foreground",
          effectiveStatus === "error" && "text-red-300"
        )}
        aria-live="polite"
      >
        {effectiveStatus === "running" && (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
        )}
        {effectiveStatus === "done" && (
          <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
        {effectiveStatus === "error" && (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-300" aria-hidden="true" />
        )}
        <span className="break-words">{label}</span>
      </div>
    </div>
  );
}
