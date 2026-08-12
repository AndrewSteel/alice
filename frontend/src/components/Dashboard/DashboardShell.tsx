"use client";

import { UserCard } from "@/components/Sidebar/UserCard";

// PROJ-77: slim header/shell for the admin Dashboard — no chat-history list,
// but the user menu (AC-A6) stays reachable exactly like on the Chat page.
export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col h-screen bg-card overflow-hidden">
      <header className="flex items-center justify-between px-4 py-3 border-b border-border bg-background shrink-0">
        <span className="font-semibold text-foreground">Alice</span>
        <UserCard variant="header" />
      </header>
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
