"use client";

import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";
import { MeinProfilSection } from "./MeinProfilSection";
import { AllgemeinSection } from "./AllgemeinSection";
import { DmsSection } from "./DmsSection";
import { NutzerVerwaltungSection } from "./NutzerVerwaltungSection";
import { VoiceProfilesSection } from "./VoiceProfilesSection";
import { ChatarchivSection } from "./ChatarchivSection";
import { MailboxSection } from "./MailboxSection";

const DEFAULT_TAB = "mein-profil";

export function SettingsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { permissions, isLoading, failed } = usePermissions();

  const [activeTab, setActiveTab] = useState(DEFAULT_TAB);

  /**
   * Fail-open gating: while permissions are loading nothing gated is shown yet
   * (the tab bar renders a skeleton). Once settled, if the fetch failed we fall
   * back to the legacy `role === "admin"` check so a network hiccup never hides
   * a real admin's tabs; otherwise we honor the granular flag — which is why a
   * non-admin with the flag set to true still sees the tab.
   */
  const can = (flag: string): boolean => {
    if (failed || !permissions) return isAdmin;
    return permissions[flag] === true;
  };

  const canDms = can("can_manage_dms_folders");
  const canUsers = can("can_manage_users");
  const canChatArchive = can("can_view_chat_archive");
  const canManageMailboxes = can("can_manage_mailboxes");
  // Voice profiles stay a deliberate admin-only bootstrap exception (see spec).
  const canVoiceProfiles = isAdmin;

  const isTabPermitted = (tab: string): boolean => {
    switch (tab) {
      case "dms": return canDms;
      case "nutzerverwaltung": return canUsers;
      case "chatarchiv": return canChatArchive;
      case "stimmprofile": return canVoiceProfiles;
      default: return true; // mein-profil, allgemein, email
    }
  };

  /**
   * Edge case: after an in-SPA user switch the active tab may be leftover state
   * from a previous (admin) session. Once permissions settle, if the active tab
   * is not permitted for the current user, fall back to the default tab instead
   * of rendering an empty/broken panel.
   */
  useEffect(() => {
    if (isLoading) return;
    if (!isTabPermitted(activeTab)) setActiveTab(DEFAULT_TAB);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, activeTab, permissions, failed]);

  const triggerClass =
    "flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted";

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border bg-background sticky top-0 z-10">
        <div className="max-w-5xl mx-auto flex items-center gap-3 px-4 py-3 md:px-6">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => { window.location.href = "/"; }}
            className="text-muted-foreground hover:text-foreground shrink-0"
            aria-label={t("settings.backToChat")}
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <h1 className="text-lg font-semibold">{t("settings.title")}</h1>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-4 py-6 md:px-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} orientation="vertical" className="w-full">
          <div className="flex flex-col md:flex-row md:gap-6">
            {/* Tab Navigation */}
            {isLoading ? (
              <div
                className="flex flex-row md:flex-col w-full md:w-44 shrink-0 gap-1 rounded-md border border-border bg-card p-1 md:h-fit md:sticky md:top-20"
                aria-hidden="true"
              >
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-8 flex-1 md:flex-none md:w-full bg-muted" />
                ))}
              </div>
            ) : (
              <TabsList className="flex flex-row md:flex-col w-full md:w-44 shrink-0 overflow-x-auto rounded-md border border-border bg-card p-1 md:h-fit md:sticky md:top-20">
                <TabsTrigger value="mein-profil" className={triggerClass}>
                  <span className="md:hidden">{t("settings.tabs.profileShort")}</span>
                  <span className="hidden md:inline">{t("settings.tabs.profile")}</span>
                </TabsTrigger>
                <TabsTrigger value="allgemein" className={triggerClass}>
                  {t("settings.tabs.allgemein")}
                </TabsTrigger>
                {canDms && (
                  <TabsTrigger value="dms" className={triggerClass}>
                    {t("settings.tabs.dms")}
                  </TabsTrigger>
                )}
                {canUsers && (
                  <TabsTrigger value="nutzerverwaltung" className={triggerClass}>
                    <span className="md:hidden">{t("settings.tabs.usersShort")}</span>
                    <span className="hidden md:inline">{t("settings.tabs.users")}</span>
                  </TabsTrigger>
                )}
                {canVoiceProfiles && (
                  <TabsTrigger value="stimmprofile" className={triggerClass}>
                    {t("settings.tabs.voiceProfiles")}
                  </TabsTrigger>
                )}
                {canChatArchive && (
                  <TabsTrigger value="chatarchiv" className={triggerClass}>
                    {t("settings.tabs.chatArchive")}
                  </TabsTrigger>
                )}
                <TabsTrigger value="email" className={triggerClass}>
                  {t("settings.tabs.email")}
                </TabsTrigger>
              </TabsList>
            )}

            {/* Tab Content */}
            <div className="mt-4 md:mt-0 flex-1 min-w-0">
              <TabsContent value="mein-profil" className="mt-0">
                <MeinProfilSection />
              </TabsContent>
              <TabsContent value="allgemein" className="mt-0">
                <AllgemeinSection />
              </TabsContent>
              {canDms && (
                <TabsContent value="dms" className="mt-0">
                  <DmsSection />
                </TabsContent>
              )}
              {canUsers && (
                <TabsContent value="nutzerverwaltung" className="mt-0">
                  <NutzerVerwaltungSection />
                </TabsContent>
              )}
              {canVoiceProfiles && (
                <TabsContent value="stimmprofile" className="mt-0">
                  <VoiceProfilesSection />
                </TabsContent>
              )}
              {canChatArchive && (
                <TabsContent value="chatarchiv" className="mt-0">
                  <ChatarchivSection />
                </TabsContent>
              )}
              <TabsContent value="email" className="mt-0">
                <MailboxSection canManageMailboxes={canManageMailboxes} />
              </TabsContent>
            </div>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
