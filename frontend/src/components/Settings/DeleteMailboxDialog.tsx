"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { Mailbox } from "@/services/mailApi";

interface Props {
  mailbox: Mailbox;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (id: string) => Promise<void>;
}

export function DeleteMailboxDialog({ mailbox, open, onOpenChange, onConfirm }: Props) {
  const { t } = useTranslation();
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setError(null);
    setDeleting(true);
    try {
      await onConfirm(mailbox.id);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.mail.deleteError"));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-card border-border text-foreground">
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.mail.deleteDialog.title")}</AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            {t("settings.mail.deleteDialog.desc", {
              name: mailbox.display_name,
              host: mailbox.imap_host,
              count: mailbox.mails_indexed,
            })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-sm text-red-400 px-1">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel
            className="bg-muted border-border text-foreground hover:bg-accent"
            disabled={deleting}
          >
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={deleting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {deleting ? t("common.deleting") : t("settings.mail.deleteDialog.confirmDelete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
