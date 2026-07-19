"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EmailUpdateInput, ProfileData } from "@/services/profileApi";

// Basic email regex for client-side validation
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface EmailFormProps {
  profile: ProfileData;
  onSave: (input: EmailUpdateInput) => Promise<void>;
}

export function EmailForm({ profile, onSave }: EmailFormProps) {
  const [email, setEmail] = useState(profile.email ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync with profile changes
  useEffect(() => {
    setEmail(profile.email ?? "");
  }, [profile]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmed = email.trim();
    if (!trimmed) {
      setError("E-Mail-Adresse darf nicht leer sein");
      return;
    }

    if (!EMAIL_REGEX.test(trimmed)) {
      setError("Ungueltige E-Mail-Adresse");
      return;
    }

    setIsSaving(true);
    try {
      await onSave({ email: trimmed });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Fehler beim Speichern. Bitte erneut versuchen."
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground">E-Mail-Adresse</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="profile-email" className="text-foreground">
              E-Mail
            </Label>
            <Input
              id="profile-email"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError(null);
              }}
              placeholder="deine@email.de"
              className="bg-card border-border text-foreground placeholder:text-muted-foreground"
            />
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
          </div>

          <Button
            type="submit"
            disabled={isSaving}
            className="bg-blue-600 hover:bg-blue-500 text-white"
          >
            {isSaving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            E-Mail speichern
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
