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
      <AlertDialogContent className="bg-gray-800 border-gray-700 text-gray-100">
        <AlertDialogHeader>
          <AlertDialogTitle>OTP zuruecksetzen?</AlertDialogTitle>
          <AlertDialogDescription className="text-gray-400">
            Ein neues Einmal-Passwort wird generiert und per E-Mail an{" "}
            <span className="font-medium text-gray-300">
              {user.email || user.username}
            </span>{" "}
            gesendet. Der Nutzer muss das Passwort beim naechsten Login aendern.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={isSubmitting}
            className="bg-transparent border-gray-600 text-gray-300 hover:bg-gray-700 hover:text-gray-100"
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
