"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * `/settings` has no panel of its own — redirect to the default tab. The shell
 * (in layout.tsx) also treats the empty segment as unknown and redirects, so a
 * skeleton is shown here rather than an empty panel while this replace runs.
 */
export default function SettingsIndexPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/settings/profil");
  }, [router]);
  return null;
}
