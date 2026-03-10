"use client";

import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { ChatWindow } from "@/components/Chat/ChatWindow";
import { useChatSessions } from "@/hooks/useChatSessions";

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);

  const {
    sessions,
    sessionsLoaded,
    sessionsLoading,
    messagesLoading,
    activeSessionId,
    messages,
    isLoading,
    createNewSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
  } = useChatSessions();

  // Auto-start: always begin with a fresh empty chat on app load.
  // Users can click on existing sessions in the sidebar to view their history.
  useEffect(() => {
    if (!sessionsLoaded) return;
    if (!activeSessionId) {
      createNewSession();
    }
  }, [sessionsLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleNewChat() {
    createNewSession();
    setMobileOpen(false);
  }

  function handleSelectSession(id: string) {
    selectSession(id);
    setMobileOpen(false);
  }

  function handleRenameSession(id: string, newTitle: string) {
    renameSession(id, newTitle);
  }

  function handleDeleteSession(id: string) {
    deleteSession(id);
  }

  // Map SessionMeta to ChatSession shape expected by Sidebar
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
    onRenameSession: handleRenameSession,
    onDeleteSession: handleDeleteSession,
    onCollapse: () => setDesktopCollapsed(true),
    onServiceLinkClick: () => setMobileOpen(false),
  };

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-gray-800 overflow-hidden">
        {/* Desktop Sidebar (fest, md+) */}
        {!desktopCollapsed && (
          <aside className="hidden md:flex flex-col w-[260px] shrink-0 border-r border-gray-700">
            <Sidebar {...sidebarProps} />
          </aside>
        )}

        {/* Mobile Sidebar (Sheet / Drawer) */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-[260px] p-0 bg-gray-900 border-gray-700">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <Sidebar {...sidebarProps} onCollapse={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        {/* Hauptbereich */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Mobile Header */}
          <header className="md:hidden flex items-center gap-2 px-4 py-3 border-b border-gray-700 bg-gray-900">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileOpen(true)}
              className="text-gray-400 hover:text-gray-100"
              aria-label="Menue oeffnen"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <span className="font-semibold text-gray-100">Alice</span>
          </header>

          {/* Desktop: collapsed-State -- Sidebar-Toggle-Button */}
          {desktopCollapsed && (
            <div className="hidden md:flex items-center px-4 py-3 border-b border-gray-700 bg-gray-900">
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

          <main className="flex-1 overflow-hidden">
            {activeSessionId ? (
              <ChatWindow
                messages={messages}
                isLoading={isLoading}
                messagesLoading={messagesLoading}
                onSend={sendMessage}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500">
                <p>Starte einen neuen Chat.</p>
              </div>
            )}
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
