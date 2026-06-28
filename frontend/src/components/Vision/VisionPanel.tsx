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
    <div className="flex flex-col h-full bg-gray-900 border-r border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 bg-gray-900 shrink-0">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Ergebnisse
          {results.length > 0 && (
            <span className="ml-1.5 text-gray-500">({results.length})</span>
          )}
        </span>
        {/* Toggle text chat button */}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-gray-400 hover:text-gray-100"
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
