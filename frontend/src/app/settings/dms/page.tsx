"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

// Route guard (can_manage_dms_folders) is enforced by the Settings shell.
const DmsSection = dynamic(
  () => import("@/components/Settings/DmsSection").then((m) => m.DmsSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function DmsPage() {
  return <DmsSection />;
}
