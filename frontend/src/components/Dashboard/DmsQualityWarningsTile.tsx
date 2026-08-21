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
  DmsDrilldownDimension,
  DmsQualityWarningsResponse,
  fetchDmsQualityWarnings,
} from "@/services/dashboardApi";

interface CountCellProps {
  count: number;
  onClick?: () => void;
}

function CountCell({ count, onClick }: CountCellProps) {
  if (count === 0) {
    return <span className="text-muted-foreground">0</span>;
  }
  if (!onClick) {
    return <span className="text-foreground">{count}</span>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="underline decoration-dotted underline-offset-2 text-foreground hover:opacity-80"
    >
      {count}
    </button>
  );
}

export function DmsQualityWarningsTile() {
  const { t } = useTranslation();
  const [data, setData] = useState<DmsQualityWarningsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<{ docType: string; dimension: DmsDrilldownDimension } | null>(
    null
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchDmsQualityWarnings()
      .then((d) => setData(d))
      .catch(() => setError(t("dashboard.dmsQualityWarnings.error")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDrilldown = (docType: string, dimension: DmsDrilldownDimension) =>
    setDrilldown({ docType, dimension });

  const hasWarnings =
    data && (data.totals.classificationUncertainCount > 0 || data.totals.languageUncertainCount > 0);

  const rows = data ? [...data.rows, data.totals] : [];

  return (
    <>
      <TileCard
        title={t("dashboard.dmsQualityWarnings.title")}
        onRefresh={load}
        refreshAriaLabel={t("dashboard.dmsQualityWarnings.refreshAria")}
        refreshing={loading}
      >
        {loading && (
          <div className="space-y-2">
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

        {!loading && !error && data && !hasWarnings && (
          <p className="text-sm text-muted-foreground">{t("dashboard.dmsQualityWarnings.empty")}</p>
        )}

        {!loading && !error && data && hasWarnings && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("dashboard.dmsQualityWarnings.columns.docType")}</TableHead>
                <TableHead>{t("dashboard.dmsQualityWarnings.columns.classificationUncertain")}</TableHead>
                <TableHead>{t("dashboard.dmsQualityWarnings.columns.languageUncertain")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const isTotal = row.docType === "total";
                return (
                  <TableRow key={row.docType} className={cn(isTotal && "font-medium bg-muted/30")}>
                    <TableCell>
                      {isTotal
                        ? t("dashboard.dmsQualityWarnings.total")
                        : t(`dashboard.dmsCoverage.docTypes.${row.docType}`, row.docType)}
                    </TableCell>
                    <TableCell>
                      <CountCell
                        count={row.classificationUncertainCount}
                        onClick={
                          isTotal ? undefined : () => openDrilldown(row.docType, "classificationUncertain")
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <CountCell
                        count={row.languageUncertainCount}
                        onClick={isTotal ? undefined : () => openDrilldown(row.docType, "languageUncertain")}
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
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
