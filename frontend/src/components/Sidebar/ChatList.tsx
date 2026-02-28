"use client";

import { useMemo } from "react";
import { ChatListItem, ChatSession } from "./ChatListItem";

interface ChatListProps {
  sessions: ChatSession[];
  activeId: string | null;
  searchQuery: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
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

export function ChatList({ sessions, activeId, searchQuery, onSelect, onDelete }: ChatListProps) {
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  const groups = useMemo(() => groupByDate(filtered), [filtered]);

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
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}
