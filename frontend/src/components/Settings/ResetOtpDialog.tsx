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

interface ResetOtpDialogProps {
  user: AdminUser;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (userId: string) => Promise<void>;
}

export function ResetOtpDialog({
  user,
  open,
  onOpenChange,
  onConfirm,
}: ResetOtpDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleConfirm() {
    setIsSubmitting(true);
    try {
      await onConfirm(user.id);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-card border-border text-foreground">
        <AlertDialogHeader>
          <AlertDialogTitle>OTP zuruecksetzen?</AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            Ein neues Einmal-Passwort wird generiert und per E-Mail an{" "}
            <span className="font-medium text-foreground">
              {user.email || user.username}
            </span>{" "}
            gesendet. Der Nutzer muss das Passwort beim naechsten Login aendern.
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
            className="bg-blue-600 hover:bg-blue-500 text-white"
          >
            {isSubmitting ? "Wird gesendet..." : "OTP senden"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
