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

interface SetCredentialsDialogProps {
  user: AdminUser;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (userId: string, email: string) => Promise<void>;
}

export function SetCredentialsDialog({
  user,
  open,
  onOpenChange,
  onConfirm,
}: SetCredentialsDialogProps) {
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleClose(next: boolean) {
    if (isSubmitting) return;
    if (!next) {
      setEmail("");
      setError(null);
    }
    onOpenChange(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await onConfirm(user.id, email.trim());
      handleClose(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 max-w-md">
        <DialogHeader>
          <DialogTitle>WebApp-Zugang einrichten</DialogTitle>
          <DialogDescription className="text-gray-400">
            E-Mail-Adresse fuer{" "}
            <span className="font-medium text-gray-300">
              {user.display_name || user.username}
            </span>{" "}
            setzen. Ein Einmal-Passwort wird per E-Mail gesendet; der Nutzer
            muss es beim ersten Login aendern.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 py-1">
          <div className="space-y-2">
            <Label htmlFor="sc-email" className="text-gray-300">
              E-Mail-Adresse
            </Label>
            <Input
              id="sc-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="nutzer@beispiel.de"
              disabled={isSubmitting}
              required
              autoComplete="email"
              className="bg-gray-700 border-gray-600 text-gray-100 placeholder-gray-500 focus:border-blue-500"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleClose(false)}
              disabled={isSubmitting}
              className="text-gray-300 hover:bg-gray-700 hover:text-gray-100"
            >
              Abbrechen
            </Button>
            <Button
              type="submit"
              disabled={!email.trim() || isSubmitting}
              className="bg-blue-600 hover:bg-blue-500 text-white"
            >
              {isSubmitting ? "Wird gespeichert..." : "Zugang einrichten"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
