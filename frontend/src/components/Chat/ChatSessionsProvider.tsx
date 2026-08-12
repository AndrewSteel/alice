"use client";

import { createContext, useContext } from "react";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useVisionPanel, UseVisionPanelReturn } from "@/hooks/useVisionPanel";

type ChatSessions = ReturnType<typeof useChatSessions>;

interface DashboardContextValue {
  chat: ChatSessions;
  vision: UseVisionPanelReturn;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

/**
 * Lifts chat-session state (PROJ-51/71) and vision-panel state (PROJ-54) one
 * level up so they survive navigation between the Dashboard and the Chat
 * page (PROJ-77). Both routes share this provider via `src/app/(main)/layout.tsx`
 * — sending a message from the Dashboard's input bar starts a stream that
 * keeps running after the view switches to the Chat page.
 */
export function ChatSessionsProvider({ children }: { children: React.ReactNode }) {
  const vision = useVisionPanel();
  const chat = useChatSessions({
    onVisionResults: vision.setResults,
    onTextResponse: vision.onTextResponse,
  });

  return (
    <DashboardContext.Provider value={{ chat, vision }}>
      {children}
    </DashboardContext.Provider>
  );
}

function useDashboardContext(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error("useDashboardContext must be used within ChatSessionsProvider");
  }
  return ctx;
}

export function useChatSessionsContext(): ChatSessions {
  return useDashboardContext().chat;
}

export function useVisionPanelContext(): UseVisionPanelReturn {
  return useDashboardContext().vision;
}
