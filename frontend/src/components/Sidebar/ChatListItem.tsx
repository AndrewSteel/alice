"use client";

import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  const [supportsHover, setSupportsHover] = useState(false);

  useEffect(() => {
    setSupportsHover(window.matchMedia("(hover: hover)").matches);
  }, []);
  const [draft, setDraft] = useState("");
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const committedRef = useRef(false);

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      committedRef.current = false;
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  function startRename() {
    setDraft(session.title);
    setIsRenaming(true);
  }

  function commitRename() {
    if (committedRef.current) return;
    committedRef.current = true;
    if (draft.trim()) {
      onRename(session.id, draft.trim());
    }
    setIsRenaming(false);
  }

  function cancelRename() {
    committedRef.current = true;
    setIsRenaming(false);
  }

  function handleDeleteConfirm() {
    setShowDeleteDialog(false);
    onDelete(session.id);
  }

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => { if (!isRenaming) onSelect(session.id); }}
        onKeyDown={(e) => { if (e.key === "Enter" && !isRenaming) onSelect(session.id); }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => { if (!menuOpen) setHovered(false); }}
        className={cn(
          "group flex items-center min-w-0 rounded-md px-3 py-2 text-sm cursor-pointer select-none transition-colors",
          isActive
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
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
            className="h-6 py-0 px-1 text-sm bg-muted border-input text-foreground focus-visible:ring-1 focus-visible:ring-ring"
          />
        ) : (
          <>
            {supportsHover ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="truncate flex-1 min-w-0">{session.title}</span>
                </TooltipTrigger>
                <TooltipContent side="top" className="bg-white text-black border-border">
                  {session.title}
                </TooltipContent>
              </Tooltip>
            ) : (
              <span className="truncate flex-1 min-w-0">{session.title}</span>
            )}
            {(hovered || menuOpen) && (
              <div className="flex items-center ml-1 shrink-0">
                <DropdownMenu open={menuOpen} onOpenChange={(open) => {
                  setMenuOpen(open);
                  if (!open) setHovered(false);
                }}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground hover:bg-accent"
                      onClick={(e) => e.stopPropagation()}
                      aria-label="Optionen"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    className="bg-card border-border w-40"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <DropdownMenuItem
                      onClick={() => startRename()}
                      className="text-foreground focus:bg-accent focus:text-foreground cursor-pointer"
                    >
                      <Pencil className="mr-2 h-4 w-4" />
                      Umbenennen
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => setShowDeleteDialog(true)}
                      className="text-red-400 focus:bg-accent focus:text-red-300 cursor-pointer"
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Loeschen
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            )}
          </>
        )}
      </div>

      {/* Delete Confirmation Dialog (AC-A6, AC-A7) */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Chat loeschen?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Der Chat &quot;{session.title}&quot; wird unwiderruflich geloescht.
              Diese Aktion kann nicht rueckgaengig gemacht werden.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted text-foreground border-border hover:bg-accent hover:text-foreground">
              Abbrechen
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              className="bg-red-600 text-white hover:bg-red-700"
            >
              Loeschen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
