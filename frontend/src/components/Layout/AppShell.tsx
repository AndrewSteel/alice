"use client";

import { useState } from "react";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { ChatSession } from "@/components/Sidebar/ChatListItem";

interface AppShellProps {
  children: React.ReactNode;
}

// Placeholder-Daten bis PROJ-8 den echten Session-Store liefert
const MOCK_SESSIONS: ChatSession[] = [];

export function AppShell({ children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [sessions] = useState<ChatSession[]>(MOCK_SESSIONS);
  const [activeId, setActiveId] = useState<string | null>(null);

  function handleNewChat() {
    setMobileOpen(false);
    // Session-Logik kommt in PROJ-8
  }

  function handleDelete(id: string) {
    console.log("delete", id); // wird in PROJ-8 implementiert
  }

  const sidebarProps = {
    sessions,
    activeSessionId: activeId,
    onNewChat: handleNewChat,
    onSelectSession: (id: string) => { setActiveId(id); setMobileOpen(false); },
    onDeleteSession: handleDelete,
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
              aria-label="Menü öffnen"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <span className="font-semibold text-gray-100">Alice</span>
          </header>

          {/* Desktop: collapsed-State — Sidebar-Toggle-Button */}
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

          <main className="flex-1 overflow-hidden">{children}</main>
        </div>
      </div>
    </TooltipProvider>
  );
}
