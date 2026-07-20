"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ChatListItem, ChatSession } from "./ChatListItem";
import { Skeleton } from "@/components/ui/skeleton";

type GroupKey = "today" | "yesterday" | "thisWeek" | "older";

interface ChatListProps {
  sessions: ChatSession[];
  activeId: string | null;
  searchQuery: string;
  onSelect: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onDelete: (id: string) => void;
  isLoading?: boolean;
}

function groupByDate(sessions: ChatSession[]): { key: GroupKey; items: ChatSession[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86400000;
  const weekAgo = today - 7 * 86400000;

  const groups: Record<GroupKey, ChatSession[]> = {
    today: [],
    yesterday: [],
    thisWeek: [],
    older: [],
  };

  for (const s of sessions) {
    const t = new Date(s.updatedAt).getTime();
    if (t >= today) groups.today.push(s);
    else if (t >= yesterday) groups.yesterday.push(s);
    else if (t >= weekAgo) groups.thisWeek.push(s);
    else groups.older.push(s);
  }

  return (Object.entries(groups) as [GroupKey, ChatSession[]][])
    .filter(([, items]) => items.length > 0)
    .map(([key, items]) => ({ key, items }));
}

function ChatListSkeleton({ label }: { label: string }) {
  return (
    <div className="space-y-4 px-2" aria-label={label}>
      <div>
        <Skeleton className="h-3 w-16 mb-2 bg-muted" />
        <div className="space-y-1">
          <Skeleton className="h-9 w-full rounded-md bg-muted/60" />
          <Skeleton className="h-9 w-full rounded-md bg-muted/60" />
          <Skeleton className="h-9 w-3/4 rounded-md bg-muted/60" />
        </div>
      </div>
    </div>
  );
}

export function ChatList({ sessions, activeId, searchQuery, onSelect, onRename, onDelete, isLoading }: ChatListProps) {
  const { t } = useTranslation();
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  const groups = useMemo(() => groupByDate(filtered), [filtered]);

  // Loading state (AC-C9)
  if (isLoading) {
    return <ChatListSkeleton label={t("sidebar.loadingLabel")} />;
  }

  if (filtered.length === 0) {
    return (
      <p className="px-3 py-4 text-sm text-muted-foreground text-center">
        {searchQuery ? t("sidebar.noResults") : t("sidebar.noChats")}
      </p>
    );
  }

  return (
    <nav aria-label={t("sidebar.historyLabel")} className="space-y-4 px-2">
      {groups.map(({ key, items }) => (
        <div key={key}>
          <p className="px-1 mb-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            {t(`sidebar.groups.${key}`)}
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
