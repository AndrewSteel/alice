"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

const AllgemeinSection = dynamic(
  () => import("@/components/Settings/AllgemeinSection").then((m) => m.AllgemeinSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function AllgemeinPage() {
  return <AllgemeinSection />;
}
