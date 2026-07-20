import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import de from "./locales/de";
import en from "./locales/en";

export type Locale = "de" | "en";
export type Sprache = "de" | "en";

export const SUPPORTED_LOCALES: Locale[] = ["de", "en"];
export const DEFAULT_LOCALE: Locale = "de";

/** Persisted client-side hint so the UI language is stable across reloads. */
export const UI_LOCALE_STORAGE_KEY = "alice_ui_locale";

/**
 * Maps the profile `sprache` value onto an i18n locale code. Accepts both the
 * PROJ-63 ISO codes ("de"/"en") and the legacy word-form values ("deutsch"/
 * "englisch") that alice-auth still reads for pre-migration profiles.
 */
export function spracheToLocale(sprache: string | null | undefined): Locale {
  return sprache === "en" || sprache === "englisch" ? "en" : "de";
}

/** Maps an i18n locale code back onto a profile `sprache` value (ISO code). */
export function localeToSprache(locale: string): Sprache {
  return locale === "en" ? "en" : "de";
}

/** BCP-47 tag for `Intl` date/number formatting following the active locale. */
export function intlLocale(locale: string): string {
  return locale === "en" ? "en-US" : "de-DE";
}

/**
 * Detects the pre-login UI language from the browser. Falls back to German
 * when the browser prefers neither German nor English (spec requirement).
 */
export function detectBrowserLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const langs = navigator.languages?.length
    ? navigator.languages
    : [navigator.language];
  for (const l of langs) {
    const code = l.toLowerCase().slice(0, 2);
    if (code === "de") return "de";
    if (code === "en") return "en";
  }
  return DEFAULT_LOCALE;
}

// Initialize the shared singleton exactly once. Rendered deterministically as
// German for the first (server + first client) paint; the actual UI language is
// applied post-mount by I18nProvider to stay hydration-safe.
if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    resources: {
      de: { translation: de },
      en: { translation: en },
    },
    lng: DEFAULT_LOCALE,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: SUPPORTED_LOCALES,
    interpolation: { escapeValue: false },
    returnNull: false,
    // A missing key in a non-source locale resolves via fallbackLng ("de").
    // Never surface a raw technical key name to the user.
    parseMissingKeyHandler: () => "",
  });
}

export default i18n;
