"use client";

import { useState } from "react";
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
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setError(null);
    setDeleting(true);
    try {
      await onConfirm(mailbox.id);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Löschen.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-gray-800 border-gray-700 text-gray-100">
        <AlertDialogHeader>
          <AlertDialogTitle>Postfach löschen?</AlertDialogTitle>
          <AlertDialogDescription className="text-gray-400">
            <strong className="text-gray-200">{mailbox.display_name}</strong> ({mailbox.imap_host}) wird dauerhaft gelöscht.
            Alle {mailbox.mails_indexed} indexierten Mails werden aus der Suche entfernt.
            Diese Aktion kann nicht rückgängig gemacht werden.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-sm text-red-400 px-1">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel
            className="bg-gray-700 border-gray-600 text-gray-200 hover:bg-gray-600"
            disabled={deleting}
          >
            Abbrechen
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={deleting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {deleting ? "Wird gelöscht..." : "Endgültig löschen"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
