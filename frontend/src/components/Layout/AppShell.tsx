"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Menu, MessageSquare } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { ChatWindow } from "@/components/Chat/ChatWindow";
import { VisionPanel } from "@/components/Vision/VisionPanel";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useVisionPanel } from "@/hooks/useVisionPanel";
import { useIsMobile } from "@/hooks/use-mobile";

const SWIPE_THRESHOLD = 50;

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);

  const vision = useVisionPanel();
  const isMobile = useIsMobile();

  // On mobile, split mode is not allowed — coerce to text or vision
  const effectiveMode = isMobile && vision.displayMode === "split"
    ? "vision"
    : vision.displayMode;

  const {
    sessions,
    sessionsLoaded,
    sessionsLoading,
    messagesLoading,
    activeSessionId,
    messages,
    isLoading,
    isStreaming,
    createNewSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
    stopStreaming,
  } = useChatSessions({
    onVisionResults: vision.setResults,
    onTextResponse: vision.onTextResponse,
  });

  useEffect(() => {
    if (!sessionsLoaded) return;
    if (!activeSessionId) {
      createNewSession();
    }
  }, [sessionsLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Mobile swipe detection ──
  const swipeTouchStartX = useRef<number | null>(null);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    swipeTouchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (swipeTouchStartX.current === null) return;
      const dx = e.changedTouches[0].clientX - swipeTouchStartX.current;
      swipeTouchStartX.current = null;

      if (Math.abs(dx) < SWIPE_THRESHOLD) return;
      if (dx > 0) {
        // Swipe right → show text
        vision.showTextPanel();
      } else {
        // Swipe left → show vision (only if vision results exist)
        if (vision.results.length > 0) {
          vision.hideTextPanel();
        }
      }
    },
    [vision]
  );

  function handleNewChat() {
    createNewSession();
    setMobileOpen(false);
  }

  function handleSelectSession(id: string) {
    selectSession(id);
    setMobileOpen(false);
  }

  const sidebarSessions = sessions.map((s) => ({
    id: s.id,
    title: s.title,
    updatedAt: s.updatedAt,
  }));

  const sidebarProps = {
    sessions: sidebarSessions,
    activeSessionId,
    sessionsLoading,
    onNewChat: handleNewChat,
    onSelectSession: handleSelectSession,
    onRenameSession: renameSession,
    onDeleteSession: deleteSession,
    onCollapse: () => setDesktopCollapsed(true),
    onServiceLinkClick: () => setMobileOpen(false),
  };

  // Layout: vision shown when displayMode is vision or split
  const showVision = effectiveMode === "vision" || effectiveMode === "split";
  const showText = effectiveMode === "text" || effectiveMode === "split";

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-gray-800 overflow-hidden">
        {/* Desktop Sidebar */}
        {!desktopCollapsed && (
          <aside className="hidden md:flex flex-col w-[260px] shrink-0 border-r border-gray-700">
            <Sidebar {...sidebarProps} />
          </aside>
        )}

        {/* Mobile Sidebar */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-[260px] p-0 bg-gray-900 border-gray-700">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <Sidebar {...sidebarProps} onCollapse={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        {/* Main area */}
        <div
          className="flex flex-col flex-1 min-w-0"
          onTouchStart={isMobile ? handleTouchStart : undefined}
          onTouchEnd={isMobile ? handleTouchEnd : undefined}
        >
          {/* Mobile Header */}
          <header className="md:hidden flex items-center gap-2 px-4 py-3 border-b border-gray-700 bg-gray-900 shrink-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileOpen(true)}
              className="text-gray-400 hover:text-gray-100"
              aria-label="Menü öffnen"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <span className="font-semibold text-gray-100">Alice</span>
            {/* Mobile: toggle between vision and text when vision panel is active */}
            {vision.results.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto text-gray-400 hover:text-gray-100"
                title={effectiveMode === "vision" ? "Chat anzeigen" : "Karten anzeigen"}
                onClick={() =>
                  effectiveMode === "vision"
                    ? vision.showTextPanel()
                    : vision.hideTextPanel()
                }
              >
                <MessageSquare className="h-5 w-5" />
              </Button>
            )}
          </header>

          {/* Desktop: collapsed sidebar toggle */}
          {desktopCollapsed && (
            <div className="hidden md:flex items-center px-4 py-3 border-b border-gray-700 bg-gray-900 shrink-0">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setDesktopCollapsed(false)}
                className="text-gray-400 hover:text-gray-100"
                aria-label="Sidebar einblenden"
              >
                <Menu className="h-5 w-5" />
              </Button>
            </div>
          )}

          {/* Split-screen content area */}
          <main className="flex flex-1 overflow-hidden">
            {/* Vision Panel — left (2/3 desktop) */}
            {showVision && (
              <div
                className={
                  effectiveMode === "split"
                    ? "flex-[2] min-w-0 overflow-hidden"
                    : "flex-1 min-w-0 overflow-hidden"
                }
              >
                <VisionPanel
                  results={vision.results}
                  textPanelVisible={showText}
                  onShowTextPanel={vision.showTextPanel}
                  onHideTextPanel={vision.hideTextPanel}
                />
              </div>
            )}

            {/* Text Panel — right (1/3 desktop when split, full otherwise) */}
            {showText && (
              <div
                className={
                  effectiveMode === "split"
                    ? "flex-[1] min-w-0 border-l border-gray-700 overflow-hidden"
                    : "flex-1 min-w-0 overflow-hidden"
                }
              >
                {activeSessionId ? (
                  <ChatWindow
                    messages={messages}
                    isLoading={isLoading}
                    messagesLoading={messagesLoading}
                    isStreaming={isStreaming}
                    onSend={sendMessage}
                    onStop={stopStreaming}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-500">
                    <p>Starte einen neuen Chat.</p>
                  </div>
                )}
              </div>
            )}
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
