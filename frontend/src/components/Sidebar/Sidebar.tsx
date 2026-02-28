"use client";

import { useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SidebarHeader } from "./SidebarHeader";
import { NewChatButton } from "./NewChatButton";
import { ChatSearch } from "./ChatSearch";
import { ChatList } from "./ChatList";
import { UserCard } from "./UserCard";
import { ChatSession } from "./ChatListItem";

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onCollapse: () => void;
}

export function Sidebar({
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onCollapse,
}: SidebarProps) {
  const [search, setSearch] = useState("");

  return (
    <div className="flex flex-col h-full bg-gray-900 w-full">
      <SidebarHeader onCollapse={onCollapse} />

      <div className="px-2 py-2 space-y-1">
        <NewChatButton onClick={onNewChat} />
        <ChatSearch value={search} onChange={setSearch} />
      </div>

      <ScrollArea className="flex-1 overflow-y-auto py-1">
        <ChatList
          sessions={sessions}
          activeId={activeSessionId}
          searchQuery={search}
          onSelect={onSelectSession}
          onDelete={onDeleteSession}
        />
      </ScrollArea>

      <UserCard />
    </div>
  );
}
