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
import type { AdminUser } from "@/services/adminApi";

interface DeactivateUserDialogProps {
  user: AdminUser;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (userId: string, isActive: boolean) => Promise<void>;
}

export function DeactivateUserDialog({
  user,
  open,
  onOpenChange,
  onConfirm,
}: DeactivateUserDialogProps) {
  const { t } = useTranslation();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const willActivate = !user.is_active;

  async function handleConfirm() {
    setIsSubmitting(true);
    try {
      await onConfirm(user.id, willActivate);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-card border-border text-foreground">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {willActivate
              ? t("settings.users.deactivateDialog.activateTitle")
              : t("settings.users.deactivateDialog.deactivateTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            {willActivate
              ? t("settings.users.deactivateDialog.activateDesc", { name: user.username })
              : t("settings.users.deactivateDialog.deactivateDesc", { name: user.username })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={isSubmitting}
            className="bg-transparent border-border text-foreground hover:bg-accent hover:text-foreground"
          >
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isSubmitting}
            className={
              willActivate
                ? "bg-emerald-600 hover:bg-emerald-500 text-white"
                : "bg-orange-600 hover:bg-orange-500 text-white"
            }
          >
            {isSubmitting
              ? t("common.saving")
              : willActivate
                ? t("settings.users.deactivateDialog.activate")
                : t("settings.users.deactivateDialog.deactivate")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
