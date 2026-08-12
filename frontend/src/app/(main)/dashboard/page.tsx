"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { DashboardShell } from "@/components/Dashboard/DashboardShell";
import { TileGrid } from "@/components/Dashboard/TileGrid";
import { InputArea } from "@/components/Chat/InputArea";
import {
  useChatSessionsContext,
  useVisionPanelContext,
} from "@/components/Chat/ChatSessionsProvider";

// PROJ-77: admin landing page — chat input pinned above a tile grid.
export default function DashboardPage() {
  const router = useRouter();
  const { sendMessageToNewSession, isLoading, isStreaming, stopStreaming } =
    useChatSessionsContext();
  const vision = useVisionPanelContext();

  const handleSend = useCallback(
    (text: string, source?: string) => {
      // Matches the Sidebar's "New Chat" button (AppShell.handleNewChat):
      // clear any vision/flip-card results left over from a previous chat
      // session before starting the new one, so they can't still be
      // showing once the view switches to Chat (AC-B2).
      vision.reset();
      // AC-B3: identical to the "New Chat" button — starts a fresh session.
      sendMessageToNewSession(text, source);
      // AC-B2: the tile view is replaced by the existing Chat view; the
      // send above already put the shared chat state into "streaming", so
      // the Chat page picks up the in-flight response immediately.
      router.push("/");
    },
    [sendMessageToNewSession, router, vision]
  );

  return (
    <DashboardShell>
      <div className="border-b border-border bg-card">
        <InputArea
          onSend={handleSend}
          disabled={isLoading}
          isStreaming={isStreaming}
          onStop={stopStreaming}
        />
      </div>
      <TileGrid />
    </DashboardShell>
  );
}
