"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

// Route guard (admin-only) is enforced by the Settings shell.
const VoiceProfilesSection = dynamic(
  () => import("@/components/Settings/VoiceProfilesSection").then((m) => m.VoiceProfilesSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function StimmprofilePage() {
  return <VoiceProfilesSection />;
}
