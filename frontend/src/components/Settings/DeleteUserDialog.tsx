"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AdminUser } from "@/services/adminApi";

interface DeleteUserDialogProps {
  user: AdminUser;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (userId: string) => Promise<void>;
}

export function DeleteUserDialog({
  user,
  open,
  onOpenChange,
  onConfirm,
}: DeleteUserDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConfirmed = confirmText === user.username;

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setConfirmText("");
      setError(null);
    }
    onOpenChange(nextOpen);
  }

  async function handleDelete() {
    if (!isConfirmed) return;

    setError(null);
    setIsSubmitting(true);
    try {
      await onConfirm(user.id);
      setConfirmText("");
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 max-w-md">
        <DialogHeader>
          <DialogTitle className="text-red-400">
            Nutzer dauerhaft loeschen
          </DialogTitle>
          <DialogDescription className="text-gray-400">
            Diese Aktion kann nicht rueckgaengig gemacht werden. Der Nutzer{" "}
            <span className="font-medium text-gray-300">{user.username}</span>{" "}
            und alle zugehoerigen Daten werden dauerhaft geloescht.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="delete-confirm" className="text-gray-300 text-sm">
              Benutzername zur Bestaetigung eingeben:
            </Label>
            <Input
              id="delete-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              disabled={isSubmitting}
              className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-red-500"
              placeholder={user.username}
              autoComplete="off"
              autoFocus
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="ghost"
            onClick={() => handleOpenChange(false)}
            disabled={isSubmitting}
            className="text-gray-300 hover:bg-gray-700 hover:text-gray-100"
          >
            Abbrechen
          </Button>
          <Button
            type="button"
            onClick={handleDelete}
            disabled={!isConfirmed || isSubmitting}
            className="bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
          >
            {isSubmitting ? "Wird geloescht..." : "Endgueltig loeschen"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
