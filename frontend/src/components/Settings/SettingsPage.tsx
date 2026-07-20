"use client";

import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { MeinProfilSection } from "./MeinProfilSection";
import { AllgemeinSection } from "./AllgemeinSection";
import { DmsSection } from "./DmsSection";
import { NutzerVerwaltungSection } from "./NutzerVerwaltungSection";
import { VoiceProfilesSection } from "./VoiceProfilesSection";
import { ChatarchivSection } from "./ChatarchivSection";
import { MailboxSection } from "./MailboxSection";

export function SettingsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

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
        <Tabs defaultValue="mein-profil" orientation="vertical" className="w-full">
          <div className="flex flex-col md:flex-row md:gap-6">
            {/* Tab Navigation */}
            <TabsList className="flex flex-row md:flex-col w-full md:w-44 shrink-0 overflow-x-auto rounded-md border border-border bg-card p-1 md:h-fit md:sticky md:top-20">
              <TabsTrigger
                value="mein-profil"
                className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
              >
                <span className="md:hidden">{t("settings.tabs.profileShort")}</span>
                <span className="hidden md:inline">{t("settings.tabs.profile")}</span>
              </TabsTrigger>
              <TabsTrigger
                value="allgemein"
                className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
              >
                {t("settings.tabs.allgemein")}
              </TabsTrigger>
              {isAdmin && (
                <TabsTrigger
                  value="dms"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
                >
                  {t("settings.tabs.dms")}
                </TabsTrigger>
              )}
              {isAdmin && (
                <TabsTrigger
                  value="nutzerverwaltung"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
                >
                  <span className="md:hidden">{t("settings.tabs.usersShort")}</span>
                  <span className="hidden md:inline">{t("settings.tabs.users")}</span>
                </TabsTrigger>
              )}
              {isAdmin && (
                <TabsTrigger
                  value="stimmprofile"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
                >
                  {t("settings.tabs.voiceProfiles")}
                </TabsTrigger>
              )}
              {isAdmin && (
                <TabsTrigger
                  value="chatarchiv"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
                >
                  {t("settings.tabs.chatArchive")}
                </TabsTrigger>
              )}
              <TabsTrigger
                value="email"
                className="flex-1 md:flex-none md:w-full md:justify-start text-muted-foreground data-[state=active]:text-foreground data-[state=active]:bg-muted"
              >
                {t("settings.tabs.email")}
              </TabsTrigger>
            </TabsList>

            {/* Tab Content */}
            <div className="mt-4 md:mt-0 flex-1 min-w-0">
              <TabsContent value="mein-profil" className="mt-0">
                <MeinProfilSection />
              </TabsContent>
              <TabsContent value="allgemein" className="mt-0">
                <AllgemeinSection />
              </TabsContent>
              {isAdmin && (
                <TabsContent value="dms" className="mt-0">
                  <DmsSection />
                </TabsContent>
              )}
              {isAdmin && (
                <TabsContent value="nutzerverwaltung" className="mt-0">
                  <NutzerVerwaltungSection />
                </TabsContent>
              )}
              {isAdmin && (
                <TabsContent value="stimmprofile" className="mt-0">
                  <VoiceProfilesSection />
                </TabsContent>
              )}
              {isAdmin && (
                <TabsContent value="chatarchiv" className="mt-0">
                  <ChatarchivSection />
                </TabsContent>
              )}
              <TabsContent value="email" className="mt-0">
                <MailboxSection />
              </TabsContent>
            </div>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
