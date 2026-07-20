import i18n, { intlLocale } from "./config";

// Central, locale-aware date/number formatting. All components format dates
// through these helpers so the format follows the active UI language
// (de-DE vs. en-US) instead of a hardcoded per-component locale string.

/** ISO date/datetime → short date in the active locale; passes other strings through. */
export function formatMetaValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString(intlLocale(i18n.language), {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      });
    }
  }
  return s;
}

/** Short numeric date (dd.MM.yyyy / MM/dd/yyyy) in the active locale. */
export function formatDate(value: string | number | Date | null): string {
  if (value === null || value === undefined || value === "") return "--";
  try {
    return new Intl.DateTimeFormat(intlLocale(i18n.language), {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(value));
  } catch {
    return String(value);
  }
}

/** Compact date+time in the active locale. */
export function formatDateTimeShort(value: string | number | Date): string {
  try {
    return new Date(value).toLocaleString(intlLocale(i18n.language), {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(value);
  }
}

/** Full date+time in the active locale. */
export function formatDateTimeFull(value: string | number | Date): string {
  try {
    return new Date(value).toLocaleString(intlLocale(i18n.language));
  } catch {
    return String(value);
  }
}
