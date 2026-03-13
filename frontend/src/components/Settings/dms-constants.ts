export const SUGGESTED_TYPES = [
  "Invoice",
  "BankStatement",
  "Document",
  "Email",
  "SecuritySettlement",
  "Contract",
] as const;

export type SuggestedType = (typeof SUGGESTED_TYPES)[number];
