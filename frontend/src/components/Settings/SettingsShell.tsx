"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";
import { SettingsGatingContext } from "./SettingsGatingContext";
import { SettingsSectionSkeleton } from "./SettingsSectionSkeleton";

const DEFAULT_SEGMENT = "profil";

/**
 * Guard type per tab:
 *  - "public": visible to every role
 *  - "admin":  admin-only bootstrap exception (voice profiles, see PROJ-66)
 *  - any other string: a system permission flag checked via the fail-open can()
 */
type TabGuard = "public" | "admin" | string;

interface TabDef {
  segment: string;
  guard: TabGuard;
  labelKey: string;
  /** Optional shorter label shown on mobile (matches the pre-PROJ-68 tab bar). */
  shortLabelKey?: string;
}

/**
 * Single source of truth for the Settings tabs. Mirrors the tabs that the
 * former monolithic SettingsPage rendered — order, guards and labels unchanged.
 * Drives both the tab bar (which tabs are visible) and the route guard (which
 * segments the current user may reach).
 */
const TAB_DEFS: TabDef[] = [
  { segment: "profil", guard: "public", labelKey: "settings.tabs.profile", shortLabelKey: "settings.tabs.profileShort" },
  { segment: "allgemein", guard: "public", labelKey: "settings.tabs.allgemein" },
  { segment: "dms", guard: "can_manage_dms_folders", labelKey: "settings.tabs.dms" },
  { segment: "nutzer", guard: "can_manage_users", labelKey: "settings.tabs.users", shortLabelKey: "settings.tabs.usersShort" },
  { segment: "stimmprofile", guard: "admin", labelKey: "settings.tabs.voiceProfiles" },
  { segment: "chatarchiv", guard: "can_view_chat_archive", labelKey: "settings.tabs.chatArchive" },
  { segment: "mail", guard: "public", labelKey: "settings.tabs.email" },
];

const triggerBase =
  "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 flex-1 md:flex-none md:w-full md:justify-start";

/**
 * Shared Settings shell (PROJ-68).
 *
 * Replaces the former local-`useState` tab switching with real routing: the tab
 * bar renders `<Link>`s to per-tab subroutes, and the active tab is derived from
 * the URL. Each subroute's Section is code-split via a dynamic import in its own
 * `page.tsx`; this shell only owns the chrome (header + tab bar) and the guard.
 *
 * Guard: the required permission for the current segment is resolved from
 * `TAB_DEFS`. While permissions load, a skeleton is shown (never a premature
 * redirect). Once settled, an unknown segment or one the user lacks permission
 * for redirects to `/settings/profil` — and the guarded `children` are NOT
 * rendered in the meantime, so protected content never flashes.
 */
export function SettingsShell({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { permissions, isLoading, failed } = usePermissions();
  const pathname = usePathname();
  const router = useRouter();

  /**
   * Fail-open gating (unchanged from PROJ-66): while permissions are loading
   * nothing gated resolves yet; once settled, a failed fetch falls back to the
   * legacy `role === "admin"` check so a network hiccup never hides an admin's
   * tabs, otherwise the granular flag is honored.
   */
  const can = (flag: string): boolean => {
    if (failed || !permissions) return isAdmin;
    return permissions[flag] === true;
  };

  const isPermitted = (guard: TabGuard): boolean => {
    if (guard === "public") return true;
    if (guard === "admin") return isAdmin;
    return can(guard);
  };

  const currentSegment = pathname.split("/")[2]; // undefined for "/settings"
  const activeTab = TAB_DEFS.find((tab) => tab.segment === currentSegment);
  const permitted = activeTab ? isPermitted(activeTab.guard) : false;

  /**
   * Route guard. Runs only once permissions have settled. An unknown segment
   * (typo or "/settings" root) or one the user lacks permission for redirects to
   * the default tab. During loading we deliberately do nothing — no premature
   * redirect and no flash of guarded content.
   */
  useEffect(() => {
    if (isLoading) return;
    if (!activeTab || !permitted) {
      router.replace(`/settings/${DEFAULT_SEGMENT}`);
    }
  }, [isLoading, activeTab, permitted, router]);

  const visibleTabs = TAB_DEFS.filter((tab) => isPermitted(tab.guard));

  const tabBarWrapper =
    "flex flex-row md:flex-col w-full md:w-44 shrink-0 rounded-md border border-border bg-card p-1 md:h-fit md:sticky md:top-20";

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
        <div className="flex flex-col md:flex-row md:gap-6">
          {/* Tab Navigation */}
          {isLoading ? (
            <div className={cn(tabBarWrapper, "gap-1")} aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-8 flex-1 md:flex-none md:w-full bg-muted" />
              ))}
            </div>
          ) : (
            <nav
              className={cn(tabBarWrapper, "overflow-x-auto")}
              aria-label={t("settings.title")}
            >
              {visibleTabs.map((tab) => {
                const isActive = tab.segment === currentSegment;
                return (
                  <Link
                    key={tab.segment}
                    href={`/settings/${tab.segment}`}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      triggerBase,
                      isActive
                        ? "bg-muted text-foreground shadow-sm"
                        : "text-muted-foreground"
                    )}
                  >
                    {tab.shortLabelKey ? (
                      <>
                        <span className="md:hidden">{t(tab.shortLabelKey)}</span>
                        <span className="hidden md:inline">{t(tab.labelKey)}</span>
                      </>
                    ) : (
                      t(tab.labelKey)
                    )}
                  </Link>
                );
              })}
            </nav>
          )}

          {/* Tab Content */}
          <div className="mt-4 md:mt-0 flex-1 min-w-0">
            {isLoading || !activeTab || !permitted ? (
              // Loading or guard redirect in flight: show a skeleton, never the
              // guarded children (which would flash protected content).
              <SettingsSectionSkeleton />
            ) : (
              <SettingsGatingContext.Provider value={{ can, isAdmin }}>
                {children}
              </SettingsGatingContext.Provider>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
