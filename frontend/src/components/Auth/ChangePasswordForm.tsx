"use client";

import { useState } from "react";
import { Eye, EyeOff, Bot, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword } from "@/services/adminApi";

interface ChangePasswordFormProps {
  onPasswordChanged: () => void;
}

export function ChangePasswordForm({
  onPasswordChanged,
}: ChangePasswordFormProps) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isTooShort = newPassword.length > 0 && newPassword.length < 8;
  const passwordsMatch =
    confirmPassword.length === 0 || newPassword === confirmPassword;
  const canSubmit =
    !isSubmitting &&
    newPassword.length >= 8 &&
    newPassword === confirmPassword;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setError(null);
    setIsSubmitting(true);

    try {
      await changePassword(newPassword);
      onPasswordChanged();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Passwort konnte nicht geaendert werden."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-900 px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            <Bot className="h-8 w-8 text-blue-500" aria-hidden />
            <span className="text-2xl font-bold text-gray-100">Alice</span>
          </div>

          <div className="flex items-center gap-2 mb-6">
            <Lock className="h-5 w-5 text-amber-400" aria-hidden />
            <p className="text-sm text-gray-400">
              Bitte aendere dein Passwort, um fortzufahren.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="w-full space-y-4"
            aria-label="Passwort aendern"
            noValidate
          >
            <div className="space-y-1.5">
              <Label htmlFor="new-password" className="text-gray-300">
                Neues Passwort
              </Label>
              <div className="relative">
                <Input
                  id="new-password"
                  type={showNew ? "text" : "password"}
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSubmitting}
                  className={`bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500 pr-10 ${
                    isTooShort ? "border-red-500" : ""
                  }`}
                  placeholder="Mindestens 8 Zeichen"
                  required
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowNew((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 transition-colors"
                  aria-label={
                    showNew ? "Passwort verbergen" : "Passwort anzeigen"
                  }
                >
                  {showNew ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
              {isTooShort && (
                <p className="text-xs text-red-400">
                  Mindestens 8 Zeichen erforderlich.
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="confirm-password" className="text-gray-300">
                Passwort wiederholen
              </Label>
              <div className="relative">
                <Input
                  id="confirm-password"
                  type={showConfirm ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isSubmitting}
                  className={`bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500 pr-10 ${
                    !passwordsMatch ? "border-red-500" : ""
                  }`}
                  placeholder="Passwort wiederholen"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 transition-colors"
                  aria-label={
                    showConfirm ? "Passwort verbergen" : "Passwort anzeigen"
                  }
                >
                  {showConfirm ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
              {!passwordsMatch && (
                <p className="text-xs text-red-400">
                  Passwoerter stimmen nicht ueberein.
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="text-sm text-red-400">
                {error}
              </p>
            )}

            <Button
              type="submit"
              disabled={!canSubmit}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
            >
              {isSubmitting ? "Wird gespeichert..." : "Passwort aendern"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
