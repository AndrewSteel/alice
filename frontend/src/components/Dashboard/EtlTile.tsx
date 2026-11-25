"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber, formatRelative } from "@/i18n/format";
import { cn } from "@/lib/utils";
import { EtlStateResponse, etlApi } from "@/services/etlApi";
import { TileCard } from "./TileCard";

const LIGHT: Record<string, string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-500",
  red: "bg-red-500",
};

/**
 * PROJ-122 dashboard tile "ETL" (AK-36/37): errors, active rebuild, last reconciliation with a
 * traffic light; a click opens the ETL page. Loads like the other tiles (on open + refresh button).
 */
export function EtlTile() {
  const { t } = useTranslation();
  const router = useRouter();
  const [data, setData] = useState<EtlStateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    etlApi
      .state()
      .then((d) => setData(d))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = data?.rebuild?.run;
  const last = data?.reconcile?.last;
  const open = () => router.push("/etl");

  return (
    <TileCard title={t("etl.tile.title")} onRefresh={load} refreshAriaLabel={t("etl.tile.refreshAria")} refreshing={loading}>
      {loading && !data && (
        <div className="space-y-2">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </div>
      )}
      {!loading && error && !data && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t("etl.tile.error")}</AlertDescription>
        </Alert>
      )}
      {data && (
        <button
          type="button"
          onClick={open}
          aria-label={t("etl.tile.open")}
          className="w-full space-y-1.5 rounded-md text-left text-sm hover:bg-accent/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          data-testid="etl-tile"
        >
          <div className="flex justify-between gap-2">
            <span className="text-muted-foreground">{t("etl.tile.errors")}</span>
            <span data-testid="etl-tile-errors" className={cn(data.counts.serious > 0 && "font-semibold text-red-600")}>
              {t("etl.tile.errorsValue", {
                serious: formatNumber(data.counts.serious),
                failed: formatNumber(data.counts.failed),
              })}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-muted-foreground">{t("etl.tile.rebuild")}</span>
            <span data-testid="etl-tile-rebuild">
              {data.rebuild === null
                ? "--"
                : data.rebuild.active && run
                  ? `${t(`etl.runStatus.${run.status}`)} ${data.rebuild.percent ?? 0} %`
                  : t("etl.tile.noRun")}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">{t("etl.tile.reconcile")}</span>
            <span className="flex items-center gap-2" data-testid="etl-tile-reconcile">
              {data.reconcile === null
                ? "--"
                : last
                  ? `${t(`etl.reconcile.states.${last.state}`)} · ${formatRelative(last.finished_at ?? last.started_at)}`
                  : t("etl.tile.none")}
              {data.light && (
                <span
                  className={cn("inline-block h-3 w-3 shrink-0 rounded-full", LIGHT[data.light])}
                  role="img"
                  aria-label={t(`etl.tile.light.${data.light}`)}
                  data-testid="etl-tile-light"
                  data-light={data.light}
                />
              )}
            </span>
          </div>
        </button>
      )}
    </TileCard>
  );
}
