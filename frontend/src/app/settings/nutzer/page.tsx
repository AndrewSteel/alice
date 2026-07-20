"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

// Route guard (can_manage_users) is enforced by the Settings shell.
const NutzerVerwaltungSection = dynamic(
  () => import("@/components/Settings/NutzerVerwaltungSection").then((m) => m.NutzerVerwaltungSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function NutzerPage() {
  return <NutzerVerwaltungSection />;
}
