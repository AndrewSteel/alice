"use client";

import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { AllgemeinSection } from "./AllgemeinSection";
import { DmsSection } from "./DmsSection";

export function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-700 bg-gray-900 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto flex items-center gap-3 px-4 py-3 md:px-6">
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
      <div className="max-w-4xl mx-auto px-4 py-6 md:px-6">
        <Tabs defaultValue="allgemein" className="w-full">
          {/* Desktop: tabs on top; Mobile: tabs at bottom via fixed positioning */}
          <TabsList className="fixed bottom-0 left-0 right-0 z-20 flex w-full rounded-none border-t border-gray-700 bg-gray-900 p-1 md:static md:w-auto md:rounded-md md:border-t-0 md:border md:border-gray-700 md:bg-gray-800">
            <TabsTrigger
              value="allgemein"
              className="flex-1 md:flex-none text-gray-400 data-[state=active]:text-gray-100 data-[state=active]:bg-gray-700"
            >
              Allgemein
            </TabsTrigger>
            {isAdmin && (
              <TabsTrigger
                value="dms"
                className="flex-1 md:flex-none text-gray-400 data-[state=active]:text-gray-100 data-[state=active]:bg-gray-700"
              >
                DMS
              </TabsTrigger>
            )}
          </TabsList>

          <div className="mt-6 pb-20 md:pb-6">
            <TabsContent value="allgemein">
              <AllgemeinSection />
            </TabsContent>
            {isAdmin && (
              <TabsContent value="dms">
                <DmsSection />
              </TabsContent>
            )}
          </div>
        </Tabs>
      </div>
    </div>
  );
}
