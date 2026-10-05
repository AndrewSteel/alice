"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

const CalendarSection = dynamic(
  () => import("@/components/Settings/CalendarSection").then((m) => m.CalendarSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function CalendarPage() {
  // Tab guard (can_use_calendar) lives in SettingsShell's TAB_DEFS.
  return <CalendarSection />;
}
