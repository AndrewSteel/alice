"use client";

import { useEffect } from "react";
import { I18nextProvider } from "react-i18next";
import i18n, {
  detectBrowserLocale,
  spracheToLocale,
  UI_LOCALE_STORAGE_KEY,
  type Locale,
} from "./config";
import { getToken } from "@/services/auth";
import { getProfile } from "@/services/profileApi";

/**
 * Applies the active UI language on top of the shared i18n singleton.
 *
 * - Pre-login: follows `navigator.language` (falls back to German).
 * - Post-login: switches to the user's saved `sprache` from their profile,
 *   overriding whatever the login screen showed.
 *
 * The language is only changed after mount (never during render) so the first
 * client paint matches the server-rendered German output — hydration-safe.
 */
export function I18nProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    let cancelled = false;

    const apply = (locale: Locale) => {
      if (cancelled) return;
      if (i18n.language !== locale) i18n.changeLanguage(locale);
      try {
        localStorage.setItem(UI_LOCALE_STORAGE_KEY, locale);
      } catch {
        // ignore storage errors (private mode etc.)
      }
    };

    // 1) Instant, flash-free hint from a previous session.
    try {
      const cached = localStorage.getItem(UI_LOCALE_STORAGE_KEY);
      if (cached === "de" || cached === "en") {
        if (i18n.language !== cached) i18n.changeLanguage(cached);
      }
    } catch {
      // ignore
    }

    // 2) Resolve the authoritative language.
    const token = getToken();
    if (!token) {
      apply(detectBrowserLocale());
      return;
    }

    getProfile()
      .then((profile) => apply(spracheToLocale(profile.preferences.sprache)))
      .catch(() => {
        // No profile (e.g. rate-limited) — keep cached/browser language.
        if (!cancelled && i18n.language !== "de" && i18n.language !== "en") {
          apply(detectBrowserLocale());
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Keep <html lang> in sync for accessibility / screen readers.
  useEffect(() => {
    const onChange = (lng: string) => {
      document.documentElement.lang = lng;
    };
    i18n.on("languageChanged", onChange);
    document.documentElement.lang = i18n.language;
    return () => {
      i18n.off("languageChanged", onChange);
    };
  }, []);

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
