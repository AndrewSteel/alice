"use client";

import { useState } from "react";
import { Eye, EyeOff, Bot, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslation } from "react-i18next";
import { changePassword } from "@/services/adminApi";

interface ChangePasswordFormProps {
  onPasswordChanged: () => void;
}

export function ChangePasswordForm({
  onPasswordChanged,
}: ChangePasswordFormProps) {
  const { t } = useTranslation();
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
          : t("auth.changePassword.genericError")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            <Bot className="h-8 w-8 text-blue-500" aria-hidden />
            <span className="text-2xl font-bold text-foreground">Alice</span>
          </div>

          <div className="flex items-center gap-2 mb-6">
            <Lock className="h-5 w-5 text-amber-400" aria-hidden />
            <p className="text-sm text-muted-foreground">
              {t("auth.changePassword.hint")}
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="w-full space-y-4"
            aria-label={t("auth.changePassword.formLabel")}
            noValidate
          >
            <div className="space-y-1.5">
              <Label htmlFor="new-password" className="text-foreground">
                {t("auth.changePassword.newPassword")}
              </Label>
              <div className="relative">
                <Input
                  id="new-password"
                  type={showNew ? "text" : "password"}
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSubmitting}
                  className={`bg-muted border-border text-foreground placeholder:text-muted-foreground focus:border-blue-500 pr-10 ${
                    isTooShort ? "border-red-500" : ""
                  }`}
                  placeholder={t("auth.changePassword.newPasswordPlaceholder")}
                  required
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowNew((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={
                    showNew ? t("auth.changePassword.hidePassword") : t("auth.changePassword.showPassword")
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
                  {t("auth.changePassword.tooShort")}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="confirm-password" className="text-foreground">
                {t("auth.changePassword.repeatPassword")}
              </Label>
              <div className="relative">
                <Input
                  id="confirm-password"
                  type={showConfirm ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isSubmitting}
                  className={`bg-muted border-border text-foreground placeholder:text-muted-foreground focus:border-blue-500 pr-10 ${
                    !passwordsMatch ? "border-red-500" : ""
                  }`}
                  placeholder={t("auth.changePassword.repeatPlaceholder")}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={
                    showConfirm ? t("auth.changePassword.hidePassword") : t("auth.changePassword.showPassword")
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
                  {t("auth.changePassword.mismatch")}
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
              {isSubmitting ? t("auth.changePassword.submitting") : t("auth.changePassword.submit")}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
