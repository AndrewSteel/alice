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

/** Relative time ("vor 3 Minuten" / "3 minutes ago", "in 5 minutes") in the active locale (PROJ-122). */
export function formatRelative(value: string | number | Date | null | undefined, now: number = Date.now()): string {
  if (value === null || value === undefined || value === "") return "--";
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return String(value);
  const diff = Math.round((t - now) / 1000);
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat(intlLocale(i18n.language), { numeric: "auto" });
  if (abs < 60) return rtf.format(diff, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

/** Duration in seconds as "2 h 5 min" / "45 s" with locale-aware units (PROJ-122). */
export function formatDuration(seconds: number): string {
  const loc = intlLocale(i18n.language);
  const unit = (n: number, u: "hour" | "minute" | "second") =>
    new Intl.NumberFormat(loc, { style: "unit", unit: u, unitDisplay: "narrow" }).format(n);
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return unit(s, "second");
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${unit(h, "hour")} ${unit(m, "minute")}` : unit(m, "minute");
}

/** Integer with locale-aware grouping (60.000 / 60,000). */
export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "--";
  return new Intl.NumberFormat(intlLocale(i18n.language)).format(n);
}
