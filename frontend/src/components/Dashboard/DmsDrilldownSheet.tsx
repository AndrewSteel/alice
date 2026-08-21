"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DmsDrilldownDimension, DmsDrilldownRow, fetchDmsDrilldown } from "@/services/dashboardApi";

interface DmsDrilldownSheetProps {
  docType: string | null;
  dimension: DmsDrilldownDimension | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Shared drilldown list for both PROJ-80 tiles (coverage gaps and quality
 * warnings) — same shape (file name, path, reason) in both cases.
 */
export function DmsDrilldownSheet({ docType, dimension, onOpenChange }: DmsDrilldownSheetProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<DmsDrilldownRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = docType !== null && dimension !== null;

  useEffect(() => {
    if (!open || !docType || !dimension) return;
    setLoading(true);
    setError(null);
    setRows(null);
    fetchDmsDrilldown(docType, dimension)
      .then((data) => setRows(data))
      .catch(() => setError(t("dashboard.dmsDrilldown.error")))
      .finally(() => setLoading(false));
  }, [open, docType, dimension, t]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>
            {t("dashboard.dmsDrilldown.title")}
            {docType ? ` — ${t(`dashboard.dmsCoverage.docTypes.${docType}`, docType)}` : ""}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-4">
          {loading && (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-2/3" />
            </div>
          )}

          {!loading && error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {!loading && !error && rows && rows.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("dashboard.dmsDrilldown.empty")}</p>
          )}

          {!loading && !error && rows && rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("dashboard.dmsDrilldown.columns.fileName")}</TableHead>
                  <TableHead>{t("dashboard.dmsDrilldown.columns.filePath")}</TableHead>
                  <TableHead>{t("dashboard.dmsDrilldown.columns.reason")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r, i) => (
                  <TableRow key={`${r.filePath}-${i}`}>
                    <TableCell className="max-w-[160px] truncate">{r.fileName}</TableCell>
                    <TableCell className="max-w-[220px] truncate text-muted-foreground">
                      {r.filePath}
                    </TableCell>
                    <TableCell>
                      {t(`dashboard.dmsDrilldown.reasons.${r.reason}`, r.reason)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
