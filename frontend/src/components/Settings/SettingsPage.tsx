"use client";

import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { AllgemeinSection } from "./AllgemeinSection";
import { DmsSection } from "./DmsSection";
import { NutzerVerwaltungSection } from "./NutzerVerwaltungSection";

export function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-700 bg-gray-900 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto flex items-center gap-3 px-4 py-3 md:px-6">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => { window.location.href = "/"; }}
            className="text-gray-400 hover:text-gray-100 shrink-0"
            aria-label="Zurueck zum Chat"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <h1 className="text-lg font-semibold">Einstellungen</h1>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-4 py-6 md:px-6">
        <Tabs defaultValue="allgemein" orientation="vertical" className="w-full">
          <div className="flex flex-col md:flex-row md:gap-6">
            {/* Tab Navigation */}
            <TabsList className="flex flex-row md:flex-col w-full md:w-44 shrink-0 overflow-x-auto rounded-md border border-gray-700 bg-gray-800 p-1 md:h-fit md:sticky md:top-20">
              <TabsTrigger
                value="allgemein"
                className="flex-1 md:flex-none md:w-full md:justify-start text-gray-400 data-[state=active]:text-gray-100 data-[state=active]:bg-gray-700"
              >
                Allgemein
              </TabsTrigger>
              {isAdmin && (
                <TabsTrigger
                  value="dms"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-gray-400 data-[state=active]:text-gray-100 data-[state=active]:bg-gray-700"
                >
                  DMS
                </TabsTrigger>
              )}
              {isAdmin && (
                <TabsTrigger
                  value="nutzerverwaltung"
                  className="flex-1 md:flex-none md:w-full md:justify-start text-gray-400 data-[state=active]:text-gray-100 data-[state=active]:bg-gray-700"
                >
                  <span className="md:hidden">Nutzer</span>
                  <span className="hidden md:inline">Nutzerverwaltung</span>
                </TabsTrigger>
              )}
            </TabsList>

            {/* Tab Content */}
            <div className="mt-4 md:mt-0 flex-1 min-w-0">
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
            </div>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
