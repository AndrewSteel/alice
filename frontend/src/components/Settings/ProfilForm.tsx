"use client";

import { useState, useEffect } from "react";
import { Loader2, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InteressenTagInput } from "./InteressenTagInput";
import type { ProfileData, ProfileUpdateInput } from "@/services/profileApi";

interface ProfilFormProps {
  profile: ProfileData;
  onSave: (input: ProfileUpdateInput) => Promise<void>;
}

export function ProfilForm({ profile, onSave }: ProfilFormProps) {
  const [name, setName] = useState(profile.facts.name ?? "");
  const [interessen, setInteressen] = useState<string[]>(
    profile.facts.interessen ?? []
  );
  const [anrede, setAnrede] = useState<"du" | "sie">(
    profile.preferences.anrede ?? "du"
  );
  const [sprache, setSprache] = useState<"deutsch" | "englisch">(
    profile.preferences.sprache ?? "deutsch"
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  // Sync with profile changes (e.g., after reload)
  useEffect(() => {
    setName(profile.facts.name ?? "");
    setInteressen(profile.facts.interessen ?? []);
    setAnrede(profile.preferences.anrede ?? "du");
    setSprache(profile.preferences.sprache ?? "deutsch");
  }, [profile]);

  function validateName(value: string): boolean {
    if (value.length > 100) {
      setNameError("Maximal 100 Zeichen");
      return false;
    }
    setNameError(null);
    return true;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!validateName(name)) return;

    const input: ProfileUpdateInput = {
      name: name.trim() || "",
      interessen,
      anrede,
      sprache,
    };

    setIsSaving(true);
    try {
      await onSave(input);
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
        <CardTitle className="text-foreground">Profildaten</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="profile-name" className="text-foreground">
              Name
            </Label>
            <Input
              id="profile-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                validateName(e.target.value);
              }}
              maxLength={100}
              placeholder="Dein Anzeigename"
              className="bg-card border-border text-foreground placeholder:text-muted-foreground"
            />
            {nameError && (
              <p className="text-sm text-red-400">{nameError}</p>
            )}
          </div>

          {/* Interessen */}
          <div className="space-y-2">
            <Label className="text-foreground">Interessen</Label>
            <InteressenTagInput tags={interessen} onChange={setInteressen} />
          </div>

          {/* Anrede */}
          <div className="space-y-2">
            <Label htmlFor="profile-anrede" className="text-foreground">
              Anrede
            </Label>
            <Select value={anrede} onValueChange={(v) => setAnrede(v as "du" | "sie")}>
              <SelectTrigger
                id="profile-anrede"
                className="bg-card border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem value="du">Du</SelectItem>
                <SelectItem value="sie">Sie</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Sprache */}
          <div className="space-y-2">
            <Label htmlFor="profile-sprache" className="text-foreground">
              Sprache
            </Label>
            <Select value={sprache} onValueChange={(v) => setSprache(v as "deutsch" | "englisch")}>
              <SelectTrigger
                id="profile-sprache"
                className="bg-card border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem value="deutsch">Deutsch</SelectItem>
                <SelectItem value="englisch">Englisch</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Read-only: Rolle */}
          <div className="space-y-1">
            <Label className="text-foreground flex items-center gap-1.5">
              Rolle
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-normal">
                <Info className="h-3 w-3" />
                Wird vom Admin verwaltet
              </span>
            </Label>
            <p className="text-muted-foreground text-sm py-2 px-3 rounded-md bg-background border border-border">
              {profile.facts.rolle ?? "Nicht gesetzt"}
            </p>
          </div>

          {/* Read-only: Detailgrad */}
          <div className="space-y-1">
            <Label className="text-foreground flex items-center gap-1.5">
              Detailgrad
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-normal">
                <Info className="h-3 w-3" />
                Wird vom Admin verwaltet
              </span>
            </Label>
            <p className="text-muted-foreground text-sm py-2 px-3 rounded-md bg-background border border-border">
              {profile.preferences.detailgrad ?? "Nicht gesetzt"}
            </p>
          </div>

          {/* Error */}
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
            Profil speichern
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
