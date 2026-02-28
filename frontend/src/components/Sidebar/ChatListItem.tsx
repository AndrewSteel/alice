"use client";

import { useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: Date;
}

interface ChatListItemProps {
  session: ChatSession;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ChatListItem({ session, isActive, onSelect, onDelete }: ChatListItemProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(session.id)}
      onKeyDown={(e) => e.key === "Enter" && onSelect(session.id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        "group flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer select-none transition-colors",
        isActive
          ? "bg-gray-700 text-gray-100"
          : "text-gray-400 hover:bg-gray-700/60 hover:text-gray-200"
      )}
    >
      <span className="truncate flex-1">{session.title}</span>
      {hovered && (
        <div className="flex items-center gap-1 ml-1 shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              // Rename-Logik kommt in PROJ-8
            }}
            className="p-0.5 text-gray-400 hover:text-gray-100"
            aria-label="Chat umbenennen"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(session.id);
            }}
            className="p-0.5 text-gray-400 hover:text-red-400"
            aria-label="Chat löschen"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
