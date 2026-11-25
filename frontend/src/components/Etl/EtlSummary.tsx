"use client";

import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatDateTimeShort, formatNumber, formatRelative } from "@/i18n/format";
import { cn } from "@/lib/utils";
import { ReconcileResult } from "@/services/etlApi";
import { useEtl } from "./EtlCommon";

export function levelTotals(r: ReconcileResult | null | undefined) {
  const levels = r?.summary?.levels ?? {};
  let gaps = 0;
  let repaired = 0;
  let reported = 0;
  for (const l of Object.values(levels)) {
    gaps += l.gaps ?? 0;
    repaired += l.repaired ?? 0;
    reported += (l.reported ?? 0) + (l.repair_failed ?? 0);
  }
  return { gaps, repaired, reported };
}

/** Top of the page: last reconciliation (highlighted when incomplete/old), active rebuild, errors (spec 1). */
export function EtlSummary() {
  const { t } = useTranslation();
  const { state, goTo } = useEtl();
  if (!state) return null;
  const rec = state.reconcile;
  const last = rec?.last ?? null;
  const tot = levelTotals(last);
  const run = state.rebuild?.run ?? null;
  const attention = rec ? rec.attention : false;

  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Card
        data-testid="etl-summary-reconcile"
        data-attention={attention ? "true" : "false"}
        className={cn(attention && "border-red-500 bg-red-500/10")}
      >
        <CardContent className="space-y-1 p-3 text-sm">
          <button type="button" className="flex items-center gap-1 font-medium hover:underline" onClick={() => goTo("reconcile")}>
            {attention && <AlertTriangle className="h-4 w-4 text-red-600" aria-hidden />}
            {t("etl.summary.reconcile")}
          </button>
          {rec === null ? (
            <p className="text-muted-foreground">--</p>
          ) : !last ? (
            <p>{t("etl.summary.noReconcile")}</p>
          ) : (
            <>
              <p>
                <span title={formatDateTimeShort(last.finished_at ?? last.started_at)}>
                  {formatRelative(last.finished_at ?? last.started_at)}
                </span>
                {" · "}
                {t(`etl.reconcile.kinds.${last.kind}`)}
                {" · "}
                <strong className={cn(last.state === "incomplete" && "text-red-600")}>
                  {t(`etl.reconcile.states.${last.state}`)}
                </strong>
              </p>
              {last.reason && <p className="break-words text-xs text-muted-foreground">{last.reason}</p>}
              <p className="text-xs">{t("etl.summary.gaps", tot)}</p>
              {attention && last.state === "complete" && (
                <p className="text-xs font-medium text-red-600">{t("etl.summary.olderThan")}</p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-1 p-3 text-sm">
          <button type="button" className="font-medium hover:underline" onClick={() => goTo("rebuild")}>
            {t("etl.summary.rebuild")}
          </button>
          {state.rebuild === null ? (
            <p className="text-muted-foreground">--</p>
          ) : state.rebuild.active && run ? (
            <p data-testid="etl-summary-rebuild">
              {t("etl.summary.rebuildShort", { status: t(`etl.runStatus.${run.status}`), percent: state.rebuild.percent ?? 0 })}
              {run.reason ? ` · ${run.reason}` : ""}
            </p>
          ) : (
            <p className="text-muted-foreground">{t("etl.summary.noActiveRebuild")}</p>
          )}
        </CardContent>
      </Card>

      <Card className={cn(state.counts.serious > 0 && "border-yellow-500")}>
        <CardContent className="space-y-1 p-3 text-sm">
          <button type="button" className="font-medium hover:underline" onClick={() => goTo("errors")}>
            {t("etl.summary.errors")}
          </button>
          <p data-testid="etl-summary-errors">
            {t("etl.summary.errorsShort", { serious: formatNumber(state.counts.serious), failed: formatNumber(state.counts.failed) })}
          </p>
          <p className="text-xs text-muted-foreground">{t("etl.summary.sources", { n: formatNumber(state.counts.sources) })}</p>
        </CardContent>
      </Card>
    </div>
  );
}
