"use client";

import { useEffect, useState } from "react";
import { getPermissions, type SystemPermissions } from "@/services/permissions";

export interface UsePermissionsResult {
  /** Loaded system permission flags, or null while loading / after a failed fetch. */
  permissions: SystemPermissions | null;
  /** True until the initial fetch settles (success or failure). */
  isLoading: boolean;
  /**
   * True when the fetch failed (network error, 5xx). Consumers use this to fail
   * open to the legacy `role === "admin"` behavior — a hiccup must never hide
   * tabs from a real admin. (A 401 is handled globally by fetchWithAuth.)
   */
  failed: boolean;
}

/**
 * Loads the current user's effective system permissions (PROJ-66).
 *
 * Fetches once on mount — intended to be called from SettingsPage so users who
 * never open Settings pay no request cost. There is deliberately no cross-mount
 * cache: a fresh mount (e.g. after an in-SPA user switch) always refetches, so
 * stale flags from a previous user are never shown.
 */
export function usePermissions(): UsePermissionsResult {
  const [permissions, setPermissions] = useState<SystemPermissions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data = await getPermissions();
        if (!active) return;
        setPermissions(data);
        setFailed(false);
      } catch {
        if (!active) return;
        setPermissions(null);
        setFailed(true);
      } finally {
        if (active) setIsLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  return { permissions, isLoading, failed };
}
