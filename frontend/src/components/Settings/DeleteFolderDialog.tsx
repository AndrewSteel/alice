"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
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
import type { DmsFolder } from "@/services/dms";

interface DeleteFolderDialogProps {
  folder: DmsFolder;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (id: number) => Promise<void>;
}

export function DeleteFolderDialog({
  folder,
  open,
  onOpenChange,
  onConfirm,
}: DeleteFolderDialogProps) {
  const { t } = useTranslation();
  const [deleting, setDeleting] = useState(false);

  async function handleConfirm() {
    setDeleting(true);
    try {
      await onConfirm(folder.id);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-card border-border text-foreground">
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.dms.deleteDialog.title")}</AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            {t("settings.dms.deleteDialog.desc", { path: folder.path })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={deleting}
            className="bg-transparent border-border text-foreground hover:bg-accent hover:text-foreground"
          >
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={deleting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {deleting ? t("common.deleting") : t("common.delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
