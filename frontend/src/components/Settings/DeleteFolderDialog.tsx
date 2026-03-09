"use client";

import { useState } from "react";
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
      <AlertDialogContent className="bg-gray-800 border-gray-700 text-gray-100">
        <AlertDialogHeader>
          <AlertDialogTitle>Ordner loeschen?</AlertDialogTitle>
          <AlertDialogDescription className="text-gray-400">
            Der Ordner{" "}
            <span className="font-mono text-gray-300">{folder.path}</span>{" "}
            wird dauerhaft entfernt. Bereits gescannte Dokumente bleiben erhalten.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={deleting}
            className="bg-transparent border-gray-600 text-gray-300 hover:bg-gray-700 hover:text-gray-100"
          >
            Abbrechen
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={deleting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {deleting ? "Wird geloescht..." : "Loeschen"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
