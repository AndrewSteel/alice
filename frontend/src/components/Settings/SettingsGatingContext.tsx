"use client";

import { createContext, useContext } from "react";

/**
 * Shared permission gating for the Settings routes (PROJ-68).
 *
 * The Settings shell resolves the fail-open `can()` helper once (from PROJ-66's
 * `usePermissions()`) and exposes it here so individual route pages — e.g. the
 * mail page needing `can_manage_mailboxes` for the MailboxSection prop — can
 * read the same flags without triggering a second permissions fetch.
 */
export interface SettingsGating {
  /** Fail-open flag check: falls back to the legacy admin role on load failure. */
  can: (flag: string) => boolean;
  isAdmin: boolean;
}

export const SettingsGatingContext = createContext<SettingsGating | null>(null);

export function useSettingsGating(): SettingsGating {
  const ctx = useContext(SettingsGatingContext);
  if (!ctx) {
    throw new Error("useSettingsGating must be used within the Settings shell");
  }
  return ctx;
}
