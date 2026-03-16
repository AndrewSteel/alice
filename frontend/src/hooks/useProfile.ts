import { useState, useEffect, useCallback } from "react";
import {
  getProfile,
  updateProfile,
  updateEmail,
  changePasswordVoluntary,
  type ProfileData,
  type ProfileUpdateInput,
  type EmailUpdateInput,
  type VoluntaryPasswordChangeInput,
} from "@/services/profileApi";

export function useProfile() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getProfile();
      setProfile(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profil konnte nicht geladen werden.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveProfile = useCallback(async (input: ProfileUpdateInput) => {
    await updateProfile(input);
    // Reload profile to reflect changes
    const data = await getProfile();
    setProfile(data);
  }, []);

  const saveEmail = useCallback(async (input: EmailUpdateInput) => {
    await updateEmail(input);
    // Reload profile to reflect changes
    const data = await getProfile();
    setProfile(data);
  }, []);

  const savePassword = useCallback(
    async (input: VoluntaryPasswordChangeInput) => {
      await changePasswordVoluntary(input);
    },
    []
  );

  return {
    profile,
    isLoading,
    error,
    reload: load,
    saveProfile,
    saveEmail,
    savePassword,
  };
}
