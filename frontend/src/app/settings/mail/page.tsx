"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";
import { useSettingsGating } from "@/components/Settings/SettingsGatingContext";

const MailboxSection = dynamic(
  () => import("@/components/Settings/MailboxSection").then((m) => m.MailboxSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function MailPage() {
  // Tab is public; managing other users' mailboxes is gated separately.
  const { can } = useSettingsGating();
  return <MailboxSection canManageMailboxes={can("can_manage_mailboxes")} />;
}
