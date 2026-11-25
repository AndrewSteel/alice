"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { AlertTriangle, LayoutDashboard, MessageSquare, RefreshCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UserCard } from "@/components/Sidebar/UserCard";
import { useAuth } from "@/hooks/useAuth";
import { formatRelative } from "@/i18n/format";
import { EtlError, etlApi } from "@/services/etlApi";
import { EtlContext, EtlContextValue, EtlPageState, FilterSelect } from "./EtlCommon";
import { EtlSummary } from "./EtlSummary";
import { EtlOverview } from "./EtlOverview";
import { EtlErrors } from "./EtlErrors";
import { EtlRebuild } from "./EtlRebuild";
import { EtlReconcile } from "./EtlReconcile";
import { EtlSourceDetail } from "./EtlSourceDetail";
import { EtlReconcileDetail } from "./EtlReconcileDetail";

const REFRESH_KEY = "alice_etl_refresh";
const REFRESH_OPTIONS = ["0", "5", "15", "60"];
type Tab = "overview" | "errors" | "rebuild" | "reconcile";

function readRefresh(): string {
  if (typeof window === "undefined") return "5";
  const v = window.localStorage.getItem(REFRESH_KEY);
  return v && REFRESH_OPTIONS.includes(v) ? v : "5";
}

/** PROJ-122: admin-only ETL status page. Non-admins are sent to the chat (AK-3). */
export function EtlPage() {
  const { user } = useAuth();
  const router = useRouter();
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (user && !isAdmin) router.replace("/");
  }, [user, isAdmin, router]);

  if (!user || !isAdmin) return null;
  return <EtlPageContent />;
}

function EtlPageContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const [refresh, setRefresh] = useState<string>("5");
  const [tick, setTick] = useState(0);
  const [tab, setTab] = useState<Tab>("overview");
  const [state, setState] = useState<EtlPageState | null>(null);
  const [stateFailed, setStateFailed] = useState(false);
  const [sectionDown, setSectionDown] = useState({ register: false, rebuild: false });
  const [kind, setKind] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [reconcileId, setReconcileId] = useState<number | null>(null);
  const [, setNow] = useState(0); // re-render relative times

  useEffect(() => setRefresh(readRefresh()), []);

  const changeRefresh = (v: string) => {
    setRefresh(v);
    window.localStorage.setItem(REFRESH_KEY, v); // AK-40
  };

  const reload = useCallback(() => setTick((n) => n + 1), []);

  // AK-39: auto refresh; "off" (0) never reloads by itself
  useEffect(() => {
    const s = Number(refresh);
    if (!s) return;
    const id = window.setInterval(() => setTick((n) => n + 1), s * 1000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const id = window.setInterval(() => setNow((n) => n + 1), 15000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    etlApi
      .state(kind || undefined, includeDeleted)
      .then((s) => {
        if (cancelled) return;
        // AK-41: when the rebuild/reconcile service is down the response carries null for its parts;
        // keep the last loaded values (marked outdated, with their own timestamp) instead of "--".
        setState((prev) => {
          if (s.services.rebuild || !prev) return { ...s, rebuild_as_of: s.services.rebuild ? s.as_of : null };
          return {
            ...s,
            rebuild: s.rebuild ?? prev.rebuild,
            reconcile: s.reconcile ?? prev.reconcile,
            rebuild_as_of: prev.rebuild_as_of ?? null,
          };
        });
        setStateFailed(false);
        // AK-41: the state call is the source of truth for service health, independent of the open tab;
        // a section that is mounted reports again on its own load in the same refresh cycle.
        setSectionDown((d) =>
          (d.register || d.rebuild) && (s.services.register || s.services.rebuild)
            ? { register: d.register && !s.services.register, rebuild: d.rebuild && !s.services.rebuild }
            : d
        );
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof EtlError && e.status === 403) {
          window.location.href = "/"; // EC-8: role taken away meanwhile
          return;
        }
        setStateFailed(true); // banner only, no toast per refresh (AK-41)
      });
    return () => {
      cancelled = true;
    };
  }, [tick, kind, includeDeleted]);

  const report = useCallback((service: "register" | "rebuild", ok: boolean) => {
    setSectionDown((d) => (d[service] === !ok ? d : { ...d, [service]: !ok }));
  }, []);

  const registerDown = stateFailed || sectionDown.register;
  const rebuildDown = stateFailed || sectionDown.rebuild || (state !== null && !state.services.rebuild);

  const ctx: EtlContextValue = useMemo(
    () => ({
      tick,
      state,
      registerDown,
      rebuildDown,
      report,
      reload,
      openSource: (id: string) => setSourceId(id),
      openReconcile: (id: number) => setReconcileId(id),
      goTo: (tb: Tab) => setTab(tb),
    }),
    [tick, state, registerDown, rebuildDown, report, reload]
  );

  return (
    <EtlContext.Provider value={ctx}>
      <div className="flex h-screen flex-col overflow-hidden bg-card">
        <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-background px-3 py-2 sm:px-4">
          <h1 className="mr-auto font-semibold text-foreground">{t("etl.title")}</h1>
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard")} className="gap-1">
            <LayoutDashboard className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">{t("etl.backDashboard")}</span>
            <span className="sr-only sm:hidden">{t("etl.backDashboard")}</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => router.push("/")} className="gap-1">
            <MessageSquare className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">{t("etl.backChat")}</span>
            <span className="sr-only sm:hidden">{t("etl.backChat")}</span>
          </Button>
          <UserCard variant="header" />
        </header>

        <main className="flex-1 overflow-y-auto overflow-x-hidden">
          <div className="mx-auto w-full max-w-6xl space-y-3 p-3 sm:p-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <FilterSelect
                label={t("etl.refresh.label")}
                value={refresh}
                onChange={(v) => changeRefresh(v || "5")}
                options={REFRESH_OPTIONS.map((o) => ({
                  value: o,
                  label: o === "0" ? t("etl.refresh.off") : t("etl.refresh.seconds", { n: o }),
                }))}
                className="w-[90px]"
              />
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={reload} aria-label={t("etl.refresh.now")}>
                <RefreshCw className="h-4 w-4" />
              </Button>
              {state && <span>{t("etl.asOf", { time: formatRelative(state.as_of) })}</span>}
              {state && (registerDown || rebuildDown) && <Badge variant="destructive">{t("etl.stale")}</Badge>}
            </div>

            {(registerDown || rebuildDown) && (
              <Alert variant="destructive" role="status">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>{t("etl.unavailable")}</AlertTitle>
                <AlertDescription className="space-y-1">
                  {registerDown && <p>{t("etl.unavailableRegister")}</p>}
                  {rebuildDown && <p>{t("etl.unavailableRebuild")}</p>}
                </AlertDescription>
              </Alert>
            )}

            {!state && !stateFailed && (
              <div className="space-y-2">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-48 w-full" />
              </div>
            )}

            {state && <EtlSummary />}

            {state && (
              <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
                <TabsList className="flex h-auto w-full flex-wrap justify-start">
                  <TabsTrigger value="overview">{t("etl.tabs.overview")}</TabsTrigger>
                  <TabsTrigger value="errors">{t("etl.tabs.errors")}</TabsTrigger>
                  <TabsTrigger value="rebuild">{t("etl.tabs.rebuild")}</TabsTrigger>
                  <TabsTrigger value="reconcile">{t("etl.tabs.reconcile")}</TabsTrigger>
                </TabsList>
                <TabsContent value="overview">
                  <EtlOverview
                    kind={kind}
                    onKind={setKind}
                    includeDeleted={includeDeleted}
                    onIncludeDeleted={setIncludeDeleted}
                  />
                </TabsContent>
                <TabsContent value="errors">
                  <EtlErrors />
                </TabsContent>
                <TabsContent value="rebuild">
                  <EtlRebuild />
                </TabsContent>
                <TabsContent value="reconcile">
                  <EtlReconcile />
                </TabsContent>
              </Tabs>
            )}
          </div>
        </main>
      </div>
      <EtlSourceDetail id={sourceId} onClose={() => setSourceId(null)} />
      <EtlReconcileDetail id={reconcileId} onClose={() => setReconcileId(null)} />
    </EtlContext.Provider>
  );
}
