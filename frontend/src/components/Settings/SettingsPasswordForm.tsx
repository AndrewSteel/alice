"use client";

import { useState } from "react";
import { Loader2, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VoluntaryPasswordChangeInput } from "@/services/profileApi";

interface SettingsPasswordFormProps {
  onSave: (input: VoluntaryPasswordChangeInput) => Promise<void>;
}

export function SettingsPasswordForm({ onSave }: SettingsPasswordFormProps) {
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
      errors.current = "Aktuelles Passwort ist erforderlich";
    }

    if (!newPassword) {
      errors.new = "Neues Passwort ist erforderlich";
    } else if (newPassword.length < 8) {
      errors.new = "Passwort muss mindestens 8 Zeichen haben";
    }

    if (!confirmPassword) {
      errors.confirm = "Passwort-Wiederholung ist erforderlich";
    } else if (newPassword !== confirmPassword) {
      errors.confirm = "Passwoerter stimmen nicht ueberein";
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
          : "Fehler beim Speichern. Bitte erneut versuchen.";

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
    <Card className="bg-gray-800 border-gray-700">
      <CardHeader>
        <CardTitle className="text-gray-100">Passwort aendern</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Current password */}
          <div className="space-y-2">
            <Label htmlFor="pw-current" className="text-gray-300">
              Aktuelles Passwort
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
                className="bg-gray-800 border-gray-600 text-gray-100 pr-10"
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowCurrent(!showCurrent)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200"
                aria-label={showCurrent ? "Passwort verbergen" : "Passwort anzeigen"}
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
            <Label htmlFor="pw-new" className="text-gray-300">
              Neues Passwort
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
                className="bg-gray-800 border-gray-600 text-gray-100 pr-10"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowNew(!showNew)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200"
                aria-label={showNew ? "Passwort verbergen" : "Passwort anzeigen"}
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
            <Label htmlFor="pw-confirm" className="text-gray-300">
              Neues Passwort wiederholen
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
                className="bg-gray-800 border-gray-600 text-gray-100 pr-10"
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowConfirm(!showConfirm)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200"
                aria-label={showConfirm ? "Passwort verbergen" : "Passwort anzeigen"}
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
            Passwort aendern
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
