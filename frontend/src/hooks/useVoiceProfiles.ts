"use client";

import { useCallback, useEffect, useState } from "react";

import {
  VoiceProfile,
  getVoiceProfiles,
  deleteVoiceProfile,
} from "@/services/voiceApi";

interface UseVoiceProfilesReturn {
  profiles: VoiceProfile[];
  isLoading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  removeProfile: (userId: string) => Promise<void>;
}

export function useVoiceProfiles(): UseVoiceProfilesReturn {
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getVoiceProfiles();
      setProfiles(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const removeProfile = useCallback(async (userId: string) => {
    await deleteVoiceProfile(userId);
    setProfiles((prev) => prev.filter((p) => p.user_id !== userId));
  }, []);

  return { profiles, isLoading, error, reload, removeProfile };
}
