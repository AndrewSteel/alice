"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      setError(err instanceof Error ? err.message : t("common.unknownError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-card border-border text-foreground max-w-md">
        <DialogHeader>
          <DialogTitle className="text-red-400">
            {t("settings.users.deleteDialog.title")}
          </DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {t("settings.users.deleteDialog.desc", { name: user.username })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="delete-confirm" className="text-foreground text-sm">
              {t("settings.users.deleteDialog.confirmLabel")}
            </Label>
            <Input
              id="delete-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              disabled={isSubmitting}
              className="bg-muted border-border text-foreground placeholder:text-muted-foreground focus:border-red-500"
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
            className="text-foreground hover:bg-accent hover:text-foreground"
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            onClick={handleDelete}
            disabled={!isConfirmed || isSubmitting}
            className="bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
          >
            {isSubmitting ? t("common.deleting") : t("settings.users.deleteDialog.confirmDelete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
