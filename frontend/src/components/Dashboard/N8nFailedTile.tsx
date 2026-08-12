"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { TileCard } from "./TileCard";
import { fetchFailedN8nExecutions, N8nFailedExecution } from "@/services/dashboardApi";
import { formatDateTimeShort } from "@/i18n/format";

const POLL_INTERVAL_MS = 30_000;

export function N8nFailedTile() {
  const { t } = useTranslation();
  const [executions, setExecutions] = useState<N8nFailedExecution[] | null>(null);
  const [extraCount, setExtraCount] = useState(0);
  const [overviewUrl, setOverviewUrl] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    fetchFailedN8nExecutions()
      .then((data) => {
        setExecutions(data.executions);
        setExtraCount(data.extra_count);
        setOverviewUrl(data.overview_url);
        setError(null);
      })
      .catch(() => setError(t("dashboard.n8nFailed.error")))
      .finally(() => setLoading(false));
  }, [t]);

  // AC-F2: auto-refresh every 30s while the dashboard is open.
  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <TileCard title={t("dashboard.n8nFailed.title")}>
      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      )}

      {!loading && error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!loading && !error && executions && executions.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("dashboard.n8nFailed.empty")}</p>
      )}

      {!loading && !error && executions && executions.length > 0 && (
        <ul className="space-y-1.5">
          {executions.map((e) => (
            <li key={e.id}>
              <a
                href={e.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between text-sm rounded-md px-1.5 py-1 -mx-1.5 hover:bg-accent transition-colors"
              >
                <span className="text-foreground truncate">{e.workflow_name}</span>
                <span className="text-xs text-muted-foreground shrink-0 ml-2">
                  {formatDateTimeShort(e.failed_at)}
                </span>
              </a>
            </li>
          ))}
          {extraCount > 0 && (
            <li>
              <a
                href={overviewUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-xs text-blue-500 hover:text-blue-400 px-1.5 pt-1"
              >
                {t("dashboard.n8nFailed.moreLink", { count: extraCount })}
              </a>
            </li>
          )}
        </ul>
      )}
    </TileCard>
  );
}
