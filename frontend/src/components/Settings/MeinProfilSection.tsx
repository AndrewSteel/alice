"use client";

import { useState } from "react";
import { Mic, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { useProfile } from "@/hooks/useProfile";
import { ProfilForm } from "./ProfilForm";
import { EmailForm } from "./EmailForm";
import { SettingsPasswordForm } from "./SettingsPasswordForm";
import { VoiceEnrollmentDialog } from "./VoiceEnrollmentDialog";
import type { ProfileUpdateInput, EmailUpdateInput, VoluntaryPasswordChangeInput } from "@/services/profileApi";

export function MeinProfilSection() {
  const { toast } = useToast();
  const { user } = useAuth();
  const { profile, isLoading, error, reload, saveProfile, saveEmail, savePassword } =
    useProfile();
  const [voiceDialogOpen, setVoiceDialogOpen] = useState(false);

  // --- Handlers ---

  async function handleSaveProfile(input: ProfileUpdateInput) {
    await saveProfile(input);
    toast({
      title: "Profil gespeichert",
    });
  }

  async function handleSaveEmail(input: EmailUpdateInput) {
    await saveEmail(input);
    toast({
      title: "E-Mail-Adresse geaendert",
    });
  }

  async function handleSavePassword(input: VoluntaryPasswordChangeInput) {
    await savePassword(input);
    toast({
      title: "Passwort geaendert",
    });
  }

  // --- Loading State ---
  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48 bg-gray-700" />
        <Skeleton className="h-64 w-full bg-gray-700" />
        <Skeleton className="h-32 w-full bg-gray-700" />
        <Skeleton className="h-48 w-full bg-gray-700" />
      </div>
    );
  }

  // --- Error State ---
  if (error || !profile) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-100">Mein Profil</h2>
        <div className="rounded-lg border border-red-800 bg-red-900/20 p-4">
          <p className="text-sm text-red-400">
            {error || "Profil konnte nicht geladen werden."}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={reload}
            className="mt-2 text-red-400 hover:text-red-300"
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Erneut versuchen
          </Button>
        </div>
      </div>
    );
  }

  // Admins may always self-enroll (bootstrap); other users only when an admin
  // has enabled it for them.
  const canEnrollVoice = user?.role === "admin" || profile.allow_voice_enrollment;

  // --- Main Content ---
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">Mein Profil</h2>
        <p className="text-sm text-gray-500">
          Angemeldet als <span className="text-gray-300">{profile.username}</span>
        </p>
      </div>

      <ProfilForm profile={profile} onSave={handleSaveProfile} />
      <EmailForm profile={profile} onSave={handleSaveEmail} />
      <SettingsPasswordForm onSave={handleSavePassword} />

      {canEnrollVoice && (
        <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-4 space-y-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-900/40">
              <Mic className="h-4 w-4 text-blue-300" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-gray-100">
                Stimmregistrierung
              </h3>
              <p className="text-sm text-gray-400">
                Nimm deine Stimme auf, damit Alice dich an Sprachgeraeten
                automatisch erkennt. Du kannst die Aufnahme jederzeit erneuern.
              </p>
            </div>
          </div>
          <Button
            onClick={() => setVoiceDialogOpen(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white gap-2"
          >
            <Mic className="h-4 w-4" />
            Stimme aufnehmen
          </Button>
        </div>
      )}

      <VoiceEnrollmentDialog
        open={voiceDialogOpen}
        onOpenChange={setVoiceDialogOpen}
        onEnrolled={() =>
          toast({ title: "Stimmregistrierung gespeichert" })
        }
      />
    </div>
  );
}
