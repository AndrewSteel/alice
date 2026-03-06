"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
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
  onRename: (id: string, newTitle: string) => void;
  onDelete: (id: string) => void;
}

export function ChatListItem({ session, isActive, onSelect, onRename, onDelete }: ChatListItemProps) {
  const [hovered, setHovered] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  function startRename() {
    setDraft(session.title);
    setIsRenaming(true);
  }

  function commitRename() {
    if (draft.trim()) {
      onRename(session.id, draft.trim());
    }
    setIsRenaming(false);
  }

  function cancelRename() {
    setIsRenaming(false);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => { if (!isRenaming) onSelect(session.id); }}
      onKeyDown={(e) => { if (e.key === "Enter" && !isRenaming) onSelect(session.id); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        "group flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer select-none transition-colors",
        isActive
          ? "bg-gray-700 text-gray-100"
          : "text-gray-400 hover:bg-gray-700/60 hover:text-gray-200"
      )}
    >
      {isRenaming ? (
        <Input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); commitRename(); }
            if (e.key === "Escape") { e.preventDefault(); cancelRename(); }
          }}
          onClick={(e) => e.stopPropagation()}
          aria-label="Chat umbenennen"
          maxLength={60}
          className="h-6 py-0 px-1 text-sm bg-gray-600 border-gray-500 text-gray-100 focus-visible:ring-1 focus-visible:ring-gray-400"
        />
      ) : (
        <>
          <span className="truncate flex-1">{session.title}</span>
          {hovered && (
            <div className="flex items-center gap-1 ml-1 shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); startRename(); }}
                className="p-0.5 text-gray-400 hover:text-gray-100"
                aria-label="Chat umbenennen"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(session.id); }}
                className="p-0.5 text-gray-400 hover:text-red-400"
                aria-label="Chat löschen"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
