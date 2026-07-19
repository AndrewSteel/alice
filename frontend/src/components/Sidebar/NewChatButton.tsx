"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface NewChatButtonProps {
  onClick: () => void;
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      className="w-full justify-start gap-2 px-3 text-foreground hover:text-foreground hover:bg-accent"
    >
      <Plus className="h-4 w-4" aria-hidden />
      Neuer Chat
    </Button>
  );
}
