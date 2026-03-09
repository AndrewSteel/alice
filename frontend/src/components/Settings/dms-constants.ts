export const SUGGESTED_TYPES = [
  "Rechnung",
  "Kontoauszug",
  "Dokument",
  "Email",
  "WertpapierAbrechnung",
  "Vertrag",
] as const;

export type SuggestedType = (typeof SUGGESTED_TYPES)[number];
