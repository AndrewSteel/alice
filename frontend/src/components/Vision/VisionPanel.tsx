"use client";

import type { VisionResult } from "@/services/api";
import { FlipCardGrid } from "./FlipCardGrid";
import { VisionEmptyState } from "./VisionEmptyState";
import { Button } from "@/components/ui/button";
import { MessageSquare, MessageSquareOff } from "lucide-react";

interface VisionPanelProps {
  results: VisionResult[];
  textPanelVisible: boolean;
  onShowTextPanel: () => void;
  onHideTextPanel: () => void;
}

export function VisionPanel({
  results,
  textPanelVisible,
  onShowTextPanel,
  onHideTextPanel,
}: VisionPanelProps) {
  return (
    <div className="flex flex-col h-full bg-background border-r border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-background shrink-0">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Ergebnisse
          {results.length > 0 && (
            <span className="ml-1.5 text-muted-foreground">({results.length})</span>
          )}
        </span>
        {/* Toggle text chat button */}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-foreground"
          title={textPanelVisible ? "Chat ausblenden" : "Chat einblenden"}
          onClick={textPanelVisible ? onHideTextPanel : onShowTextPanel}
        >
          {textPanelVisible ? (
            <MessageSquareOff className="h-4 w-4" />
          ) : (
            <MessageSquare className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Card grid — scrollable */}
      <div className="flex-1 overflow-y-auto">
        {results.length === 0 ? (
          <VisionEmptyState />
        ) : (
          <FlipCardGrid results={results} />
        )}
      </div>
    </div>
  );
}
