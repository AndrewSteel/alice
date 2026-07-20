"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

const MeinProfilSection = dynamic(
  () => import("@/components/Settings/MeinProfilSection").then((m) => m.MeinProfilSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function ProfilPage() {
  return <MeinProfilSection />;
}
