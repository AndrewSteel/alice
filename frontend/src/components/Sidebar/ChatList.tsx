"use client";

import { useMemo } from "react";
import { ChatListItem, ChatSession } from "./ChatListItem";
import { Skeleton } from "@/components/ui/skeleton";

interface ChatListProps {
  sessions: ChatSession[];
  activeId: string | null;
  searchQuery: string;
  onSelect: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onDelete: (id: string) => void;
  isLoading?: boolean;
}

function groupByDate(sessions: ChatSession[]): { label: string; items: ChatSession[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86400000;
  const weekAgo = today - 7 * 86400000;

  const groups: Record<string, ChatSession[]> = {
    Heute: [],
    Gestern: [],
    "Diese Woche": [],
    Älter: [],
  };

  for (const s of sessions) {
    const t = new Date(s.updatedAt).getTime();
    if (t >= today) groups["Heute"].push(s);
    else if (t >= yesterday) groups["Gestern"].push(s);
    else if (t >= weekAgo) groups["Diese Woche"].push(s);
    else groups["Älter"].push(s);
  }

  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}

function ChatListSkeleton() {
  return (
    <div className="space-y-4 px-2" aria-label="Sessions werden geladen">
      <div>
        <Skeleton className="h-3 w-16 mb-2 bg-gray-700" />
        <div className="space-y-1">
          <Skeleton className="h-9 w-full rounded-md bg-gray-700/60" />
          <Skeleton className="h-9 w-full rounded-md bg-gray-700/60" />
          <Skeleton className="h-9 w-3/4 rounded-md bg-gray-700/60" />
        </div>
      </div>
    </div>
  );
}

export function ChatList({ sessions, activeId, searchQuery, onSelect, onRename, onDelete, isLoading }: ChatListProps) {
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  const groups = useMemo(() => groupByDate(filtered), [filtered]);

  // Loading state (AC-C9)
  if (isLoading) {
    return <ChatListSkeleton />;
  }

  if (filtered.length === 0) {
    return (
      <p className="px-3 py-4 text-sm text-gray-500 text-center">
        {searchQuery ? "Keine Ergebnisse" : "Noch keine Chats"}
      </p>
    );
  }

  return (
    <nav aria-label="Chat-Verlauf" className="space-y-4 px-2">
      {groups.map(({ label, items }) => (
        <div key={label}>
          <p className="px-1 mb-1 text-xs font-medium text-gray-500 uppercase tracking-wider">
            {label}
          </p>
          <div className="space-y-0.5">
            {items.map((s) => (
              <ChatListItem
                key={s.id}
                session={s}
                isActive={s.id === activeId}
                onSelect={onSelect}
                onRename={onRename}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}
