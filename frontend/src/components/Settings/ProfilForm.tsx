"use client";

import { useState, useEffect } from "react";
import { Loader2, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import i18n, { spracheToLocale, UI_LOCALE_STORAGE_KEY } from "@/i18n/config";
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
  const { t } = useTranslation();
  const [name, setName] = useState(profile.facts.name ?? "");
  const [interessen, setInteressen] = useState<string[]>(
    profile.facts.interessen ?? []
  );
  const [anrede, setAnrede] = useState<"du" | "sie">(
    profile.preferences.anrede ?? "du"
  );
  const [sprache, setSprache] = useState<"de" | "en">(
    spracheToLocale(profile.preferences.sprache)
  );
  const [bilderAnzahl, setBilderAnzahl] = useState<number>(
    profile.preferences.bilder_standardanzahl ?? 5
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [bilderAnzahlError, setBilderAnzahlError] = useState<string | null>(null);

  // Sync with profile changes (e.g., after reload)
  useEffect(() => {
    setName(profile.facts.name ?? "");
    setInteressen(profile.facts.interessen ?? []);
    setAnrede(profile.preferences.anrede ?? "du");
    setSprache(spracheToLocale(profile.preferences.sprache));
    setBilderAnzahl(profile.preferences.bilder_standardanzahl ?? 5);
  }, [profile]);

  function validateName(value: string): boolean {
    if (value.length > 100) {
      setNameError(t("settings.profilForm.nameMaxError"));
      return false;
    }
    setNameError(null);
    return true;
  }

  function validateBilderAnzahl(value: number): boolean {
    if (!Number.isInteger(value) || value < 1 || value > 100) {
      setBilderAnzahlError(t("settings.profilForm.imageResultCountError"));
      return false;
    }
    setBilderAnzahlError(null);
    return true;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!validateName(name)) return;
    if (!validateBilderAnzahl(bilderAnzahl)) return;

    const input: ProfileUpdateInput = {
      name: name.trim() || "",
      interessen,
      anrede,
      sprache,
      bilder_standardanzahl: bilderAnzahl,
    };

    setIsSaving(true);
    try {
      await onSave(input);
      // PROJ-62: the saved `sprache` value also drives the UI language.
      const locale = spracheToLocale(sprache);
      if (i18n.language !== locale) i18n.changeLanguage(locale);
      try {
        localStorage.setItem(UI_LOCALE_STORAGE_KEY, locale);
      } catch {
        // ignore storage errors
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.profilForm.saveError")
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground">{t("settings.profilForm.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="profile-name" className="text-foreground">
              {t("settings.profilForm.name")}
            </Label>
            <Input
              id="profile-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                validateName(e.target.value);
              }}
              maxLength={100}
              placeholder={t("settings.profilForm.namePlaceholder")}
              className="bg-card border-border text-foreground placeholder:text-muted-foreground"
            />
            {nameError && (
              <p className="text-sm text-red-400">{nameError}</p>
            )}
          </div>

          {/* Interessen */}
          <div className="space-y-2">
            <Label className="text-foreground">{t("settings.profilForm.interests")}</Label>
            <InteressenTagInput tags={interessen} onChange={setInteressen} />
          </div>

          {/* Anrede */}
          <div className="space-y-2">
            <Label htmlFor="profile-anrede" className="text-foreground">
              {t("settings.profilForm.anrede")}
            </Label>
            <Select value={anrede} onValueChange={(v) => setAnrede(v as "du" | "sie")}>
              <SelectTrigger
                id="profile-anrede"
                className="bg-card border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem value="du">{t("settings.profilForm.anredeDu")}</SelectItem>
                <SelectItem value="sie">{t("settings.profilForm.anredeSie")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Sprache */}
          <div className="space-y-2">
            <Label htmlFor="profile-sprache" className="text-foreground">
              {t("settings.profilForm.language")}
            </Label>
            <Select value={sprache} onValueChange={(v) => setSprache(v as "de" | "en")}>
              <SelectTrigger
                id="profile-sprache"
                className="bg-card border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem value="de">{t("settings.profilForm.langDe")}</SelectItem>
                <SelectItem value="en">{t("settings.profilForm.langEn")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Standardanzahl Bilderergebnisse (PROJ-75) */}
          <div className="space-y-2">
            <Label htmlFor="profile-bilder-anzahl" className="text-foreground">
              {t("settings.profilForm.imageResultCount")}
            </Label>
            <Input
              id="profile-bilder-anzahl"
              type="number"
              min={1}
              max={100}
              value={bilderAnzahl}
              onChange={(e) => {
                const value = parseInt(e.target.value, 10);
                setBilderAnzahl(Number.isNaN(value) ? 0 : value);
                validateBilderAnzahl(value);
              }}
              className="bg-card border-border text-foreground placeholder:text-muted-foreground"
            />
            {bilderAnzahlError && (
              <p className="text-sm text-red-400">{bilderAnzahlError}</p>
            )}
          </div>

          {/* Read-only: Rolle */}
          <div className="space-y-1">
            <Label className="text-foreground flex items-center gap-1.5">
              {t("settings.profilForm.role")}
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-normal">
                <Info className="h-3 w-3" />
                {t("settings.profilForm.managedByAdmin")}
              </span>
            </Label>
            <p className="text-muted-foreground text-sm py-2 px-3 rounded-md bg-background border border-border">
              {profile.facts.rolle ?? t("common.notSet")}
            </p>
          </div>

          {/* Read-only: Detailgrad */}
          <div className="space-y-1">
            <Label className="text-foreground flex items-center gap-1.5">
              {t("settings.profilForm.detailLevel")}
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-normal">
                <Info className="h-3 w-3" />
                {t("settings.profilForm.managedByAdmin")}
              </span>
            </Label>
            <p className="text-muted-foreground text-sm py-2 px-3 rounded-md bg-background border border-border">
              {profile.preferences.detailgrad ?? t("common.notSet")}
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
            {t("settings.profilForm.submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
