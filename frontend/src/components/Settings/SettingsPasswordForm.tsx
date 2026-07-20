"use client";

import { useState } from "react";
import { Loader2, Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VoluntaryPasswordChangeInput } from "@/services/profileApi";

interface SettingsPasswordFormProps {
  onSave: (input: VoluntaryPasswordChangeInput) => Promise<void>;
}

export function SettingsPasswordForm({ onSave }: SettingsPasswordFormProps) {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function validate(): boolean {
    const errors: Record<string, string> = {};

    if (!currentPassword) {
      errors.current = t("settings.password.currentRequired");
    }

    if (!newPassword) {
      errors.new = t("settings.password.newRequired");
    } else if (newPassword.length < 8) {
      errors.new = t("settings.password.minLength");
    }

    if (!confirmPassword) {
      errors.confirm = t("settings.password.repeatRequired");
    } else if (newPassword !== confirmPassword) {
      errors.confirm = t("settings.password.mismatch");
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldErrors({});

    if (!validate()) return;

    setIsSaving(true);
    try {
      await onSave({
        current_password: currentPassword,
        new_password: newPassword,
      });
      // Success: clear all fields
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : t("settings.profilForm.saveError");

      // Map specific backend errors to inline field errors
      if (message.includes("Aktuelles Passwort ist falsch")) {
        setFieldErrors({ current: message });
      } else if (message.includes("unterscheiden")) {
        setFieldErrors({ new: message });
      } else if (message.includes("mindestens 8 Zeichen")) {
        setFieldErrors({ new: message });
      } else {
        setError(message);
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground">{t("settings.password.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Current password */}
          <div className="space-y-2">
            <Label htmlFor="pw-current" className="text-foreground">
              {t("settings.password.current")}
            </Label>
            <div className="relative">
              <Input
                id="pw-current"
                type={showCurrent ? "text" : "password"}
                value={currentPassword}
                onChange={(e) => {
                  setCurrentPassword(e.target.value);
                  setFieldErrors((prev) => {
                    const next = { ...prev };
                    delete next.current;
                    return next;
                  });
                }}
                className="bg-card border-border text-foreground pr-10"
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowCurrent(!showCurrent)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showCurrent ? t("auth.changePassword.hidePassword") : t("auth.changePassword.showPassword")}
              >
                {showCurrent ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            {fieldErrors.current && (
              <p className="text-sm text-red-400">{fieldErrors.current}</p>
            )}
          </div>

          {/* New password */}
          <div className="space-y-2">
            <Label htmlFor="pw-new" className="text-foreground">
              {t("settings.password.new")}
            </Label>
            <div className="relative">
              <Input
                id="pw-new"
                type={showNew ? "text" : "password"}
                value={newPassword}
                onChange={(e) => {
                  setNewPassword(e.target.value);
                  setFieldErrors((prev) => {
                    const next = { ...prev };
                    delete next.new;
                    return next;
                  });
                }}
                className="bg-card border-border text-foreground pr-10"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowNew(!showNew)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showNew ? t("auth.changePassword.hidePassword") : t("auth.changePassword.showPassword")}
              >
                {showNew ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            {fieldErrors.new && (
              <p className="text-sm text-red-400">{fieldErrors.new}</p>
            )}
          </div>

          {/* Confirm password */}
          <div className="space-y-2">
            <Label htmlFor="pw-confirm" className="text-foreground">
              {t("settings.password.repeat")}
            </Label>
            <div className="relative">
              <Input
                id="pw-confirm"
                type={showConfirm ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value);
                  setFieldErrors((prev) => {
                    const next = { ...prev };
                    delete next.confirm;
                    return next;
                  });
                }}
                className="bg-card border-border text-foreground pr-10"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowConfirm(!showConfirm)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showConfirm ? t("auth.changePassword.hidePassword") : t("auth.changePassword.showPassword")}
              >
                {showConfirm ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            {fieldErrors.confirm && (
              <p className="text-sm text-red-400">{fieldErrors.confirm}</p>
            )}
          </div>

          {/* General error */}
          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          {/* Submit */}
          <Button
            type="submit"
            disabled={isSaving}
            className="bg-blue-600 hover:bg-blue-500 text-white"
          >
            {isSaving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {t("settings.password.submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
