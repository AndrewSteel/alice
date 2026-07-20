"use client";

import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

interface NewChatButtonProps {
  onClick: () => void;
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  const { t } = useTranslation();
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      className="w-full justify-start gap-2 px-3 text-foreground hover:text-foreground hover:bg-accent"
    >
      <Plus className="h-4 w-4" aria-hidden />
      {t("sidebar.newChat")}
    </Button>
  );
}
