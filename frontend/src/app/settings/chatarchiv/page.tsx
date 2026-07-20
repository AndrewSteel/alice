"use client";

import dynamic from "next/dynamic";
import { SettingsSectionSkeleton } from "@/components/Settings/SettingsSectionSkeleton";

// Route guard (can_view_chat_archive) is enforced by the Settings shell.
const ChatarchivSection = dynamic(
  () => import("@/components/Settings/ChatarchivSection").then((m) => m.ChatarchivSection),
  { ssr: false, loading: () => <SettingsSectionSkeleton /> }
);

export default function ChatarchivPage() {
  return <ChatarchivSection />;
}
