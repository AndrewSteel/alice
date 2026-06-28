"use client";

import { useCallback, useState } from "react";
import type { VisionResult } from "@/services/api";

export type DisplayMode = "text" | "vision" | "split";

export interface UseVisionPanelReturn {
  displayMode: DisplayMode;
  results: VisionResult[];
  /** Called when vision_results SSE event arrives — switches to vision mode. */
  setResults: (results: VisionResult[]) => void;
  /** Called when a text-only LLM response arrives while in vision mode. */
  onTextResponse: () => void;
  showTextPanel: () => void;
  hideTextPanel: () => void;
}

export function useVisionPanel(): UseVisionPanelReturn {
  const [displayMode, setDisplayMode] = useState<DisplayMode>("text");
  const [results, setResultsState] = useState<VisionResult[]>([]);

  const setResults = useCallback((newResults: VisionResult[]) => {
    setResultsState(newResults);
    setDisplayMode("vision");
  }, []);

  const onTextResponse = useCallback(() => {
    setDisplayMode((prev) => (prev === "vision" ? "split" : prev));
  }, []);

  const showTextPanel = useCallback(() => {
    setDisplayMode((prev) => (prev === "vision" ? "split" : prev));
  }, []);

  const hideTextPanel = useCallback(() => {
    setDisplayMode((prev) => (prev === "split" ? "vision" : prev));
  }, []);

  return {
    displayMode,
    results,
    setResults,
    onTextResponse,
    showTextPanel,
    hideTextPanel,
  };
}
