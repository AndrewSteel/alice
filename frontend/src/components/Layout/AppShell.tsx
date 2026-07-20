"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Menu, MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { ChatWindow } from "@/components/Chat/ChatWindow";
import { InputArea } from "@/components/Chat/InputArea";
import { VisionPanel } from "@/components/Vision/VisionPanel";
import { useChatSessions } from "@/hooks/useChatSessions";
import { useVisionPanel } from "@/hooks/useVisionPanel";
import { useIsMobile } from "@/hooks/use-mobile";

const SWIPE_THRESHOLD = 50;

export function AppShell() {
  const { t } = useTranslation();
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
    vision.reset();
    setMobileOpen(false);
  }

  // Mobile/narrow viewports have no split mode — toggling must switch the
  // whole view between text-only and vision-only. On desktop the split-based
  // show/hide handlers apply.
  const onShowText = isMobile
    ? () => vision.setDisplayMode("text")
    : vision.showTextPanel;
  const onHideText = isMobile
    ? () => vision.setDisplayMode("vision")
    : vision.hideTextPanel;

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
      <div className="flex h-screen bg-card overflow-hidden">
        {/* Desktop Sidebar */}
        {!desktopCollapsed && (
          <aside className="hidden md:flex flex-col w-[260px] shrink-0 border-r border-border">
            <Sidebar {...sidebarProps} />
          </aside>
        )}

        {/* Mobile Sidebar */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-[260px] p-0 bg-background border-border">
            <SheetTitle className="sr-only">{t("chat.shell.navigation")}</SheetTitle>
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
          <header className="md:hidden flex items-center gap-2 px-4 py-3 border-b border-border bg-background shrink-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileOpen(true)}
              className="text-muted-foreground hover:text-foreground"
              aria-label={t("chat.shell.openMenu")}
            >
              <Menu className="h-5 w-5" />
            </Button>
            <span className="font-semibold text-foreground">Alice</span>
            {/* Mobile: toggle between vision and text when vision panel is active */}
            {vision.results.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto text-muted-foreground hover:text-foreground"
                title={effectiveMode === "vision" ? t("chat.shell.showChat") : t("chat.shell.showCards")}
                onClick={() =>
                  effectiveMode === "vision" ? onShowText() : onHideText()
                }
              >
                <MessageSquare className="h-5 w-5" />
              </Button>
            )}
          </header>

          {/* Desktop: collapsed sidebar toggle */}
          {desktopCollapsed && (
            <div className="hidden md:flex items-center px-4 py-3 border-b border-border bg-background shrink-0">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setDesktopCollapsed(false)}
                className="text-muted-foreground hover:text-foreground"
                aria-label={t("chat.shell.expandSidebar")}
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
                  onShowTextPanel={onShowText}
                  onHideTextPanel={onHideText}
                />
              </div>
            )}

            {/* Text Panel — right (1/3 desktop when split, full otherwise) */}
            {showText && (
              <div
                className={
                  effectiveMode === "split"
                    ? "flex-[1] min-w-0 border-l border-border overflow-hidden"
                    : "flex-1 min-w-0 overflow-hidden"
                }
              >
                {activeSessionId ? (
                  <ChatWindow
                    messages={messages}
                    isLoading={isLoading}
                    messagesLoading={messagesLoading}
                    isStreaming={isStreaming}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    <p>{t("chat.shell.startNewChat")}</p>
                  </div>
                )}
              </div>
            )}
          </main>

          {/* Persistent footer — input + voice always reachable regardless of
              which panel(s) are visible (Vision-only, Text-only, or Split). */}
          <footer className="shrink-0 border-t border-border bg-card">
            <InputArea
              onSend={sendMessage}
              disabled={isLoading || !!messagesLoading || !activeSessionId}
              isStreaming={isStreaming}
              onStop={stopStreaming}
            />
          </footer>
        </div>
      </div>
    </TooltipProvider>
  );
}
