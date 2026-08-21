"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { TileCard } from "./TileCard";
import { DmsDrilldownSheet } from "./DmsDrilldownSheet";
import {
  DmsCoverageResponse,
  DmsCoverageRow,
  DmsCoverageStatus,
  DmsDrilldownDimension,
  fetchDmsCoverage,
} from "@/services/dashboardApi";

const STATUS_DOT: Record<DmsCoverageStatus, string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-500",
  red: "bg-red-500",
  neutral: "bg-muted-foreground/30",
  error: "bg-muted-foreground/30",
  "n/a": "bg-transparent",
};

function formatPct(pct: number | null): string {
  return pct === null ? "" : `${Math.round(pct)}%`;
}

interface CoverageCellProps {
  pct: number | null;
  status: DmsCoverageStatus;
  naLabel: string;
  noDataLabel: string;
  clickable: boolean;
  onClick?: () => void;
}

function CoverageCell({ pct, status, naLabel, noDataLabel, clickable, onClick }: CoverageCellProps) {
  if (status === "n/a") {
    return <span className="text-muted-foreground">{naLabel}</span>;
  }
  if (status === "error") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (pct === null) {
    return <span className="text-muted-foreground">{noDataLabel}</span>;
  }
  const canClick = clickable && pct < 100 && onClick;
  return (
    <button
      type="button"
      disabled={!canClick}
      onClick={canClick ? onClick : undefined}
      className={cn(
        "inline-flex items-center gap-1.5",
        canClick && "underline decoration-dotted underline-offset-2 hover:text-foreground"
      )}
    >
      <span className={cn("h-2 w-2 rounded-full shrink-0", STATUS_DOT[status])} />
      {formatPct(pct)}
    </button>
  );
}

export function DmsCoverageTile() {
  const { t } = useTranslation();
  const [data, setData] = useState<DmsCoverageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<{ docType: string; dimension: DmsDrilldownDimension } | null>(
    null
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchDmsCoverage()
      .then((d) => setData(d))
      .catch(() => setError(t("dashboard.dmsCoverage.error")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDrilldown = (docType: string, dimension: DmsDrilldownDimension) =>
    setDrilldown({ docType, dimension });

  const rows: DmsCoverageRow[] = data ? [...data.rows, data.totals] : [];

  return (
    <>
      <TileCard
        title={t("dashboard.dmsCoverage.title")}
        onRefresh={load}
        refreshAriaLabel={t("dashboard.dmsCoverage.refreshAria")}
        refreshing={loading}
        className="sm:w-[560px]"
      >
        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-2/3" />
          </div>
        )}

        {!loading && error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!loading && !error && data && (
          <div className="space-y-2">
            {data.redisError && (
              <Alert variant="default" className="py-2">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription className="text-xs">
                  {t("dashboard.dmsCoverage.redisError")}
                </AlertDescription>
              </Alert>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("dashboard.dmsCoverage.columns.docType")}</TableHead>
                  <TableHead>{t("dashboard.dmsCoverage.columns.pathScan")}</TableHead>
                  <TableHead>{t("dashboard.dmsCoverage.columns.thumbnail")}</TableHead>
                  <TableHead>{t("dashboard.dmsCoverage.columns.geo")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const isTotal = row.docType === "total";
                  return (
                    <TableRow key={row.docType} className={cn(isTotal && "font-medium bg-muted/30")}>
                      <TableCell>
                        {isTotal
                          ? t("dashboard.dmsCoverage.total")
                          : t(`dashboard.dmsCoverage.docTypes.${row.docType}`, row.docType)}
                      </TableCell>
                      <TableCell>
                        <CoverageCell
                          pct={row.pathScanCoveragePct}
                          status={row.pathScanStatus}
                          naLabel={t("dashboard.dmsCoverage.naValue")}
                          noDataLabel={t("dashboard.dmsCoverage.noData")}
                          clickable={false}
                        />
                      </TableCell>
                      <TableCell>
                        <CoverageCell
                          pct={row.thumbnailCoveragePct}
                          status={row.thumbnailStatus}
                          naLabel={t("dashboard.dmsCoverage.naValue")}
                          noDataLabel={t("dashboard.dmsCoverage.noData")}
                          clickable={!isTotal}
                          onClick={() => openDrilldown(row.docType, "thumbnail")}
                        />
                      </TableCell>
                      <TableCell>
                        <CoverageCell
                          pct={row.geoCoveragePct}
                          status={row.geoStatus}
                          naLabel={t("dashboard.dmsCoverage.naValue")}
                          noDataLabel={t("dashboard.dmsCoverage.noData")}
                          clickable={!isTotal}
                          onClick={() => openDrilldown(row.docType, "geo")}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </TileCard>

      <DmsDrilldownSheet
        docType={drilldown?.docType ?? null}
        dimension={drilldown?.dimension ?? null}
        onOpenChange={(open) => {
          if (!open) setDrilldown(null);
        }}
      />
    </>
  );
}
