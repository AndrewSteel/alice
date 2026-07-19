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
            Nutzer {willActivate ? "aktivieren" : "deaktivieren"}?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            {willActivate ? (
              <>
                <span className="font-medium text-foreground">
                  {user.username}
                </span>{" "}
                wird wieder aktiviert und kann sich erneut einloggen.
              </>
            ) : (
              <>
                <span className="font-medium text-foreground">
                  {user.username}
                </span>{" "}
                wird deaktiviert und kann sich danach nicht mehr einloggen.
                Die Daten bleiben erhalten.
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={isSubmitting}
            className="bg-transparent border-border text-foreground hover:bg-accent hover:text-foreground"
          >
            Abbrechen
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
              ? "Wird gespeichert..."
              : willActivate
                ? "Aktivieren"
                : "Deaktivieren"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
