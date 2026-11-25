"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration } from "@/i18n/format";
import { cn } from "@/lib/utils";
import { etlApi } from "@/services/etlApi";
import { AbsTime, ConfirmDialog, EmptyState, Pager, ScrollBox, useEtl, useEtlAction, useEtlData } from "./EtlCommon";
import { levelTotals } from "./EtlSummary";

const RESULT_PAGE = 20;

/** Reconciliation: on demand, full re-hash (with confirmation), list of results (AK-31, AK-33, AK-34). */
export function EtlReconcile() {
  const { t } = useTranslation();
  const { state, rebuildDown, openReconcile } = useEtl();
  const act = useEtlAction();
  const [confirmRehash, setConfirmRehash] = useState(false);
  const [offset, setOffset] = useState(0);
  const { data, loading } = useEtlData(() => etlApi.results(RESULT_PAGE, offset), String(offset), "rebuild");
  const running = state?.reconcile?.running ?? null;
  const disabled = rebuildDown || running !== null || state?.reconcile === null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={disabled}
          onClick={() => act(() => etlApi.reconcileNow(), () => t("etl.reconcile.started"))}
          data-testid="etl-reconcile-now"
        >
          {t("etl.reconcile.now")}
        </Button>
        <Button variant="outline" disabled={disabled} onClick={() => setConfirmRehash(true)} data-testid="etl-reconcile-rehash">
          {t("etl.reconcile.fullRehash")}
        </Button>
        {running !== null && (
          <span className="text-sm text-muted-foreground" data-testid="etl-reconcile-running">
            {t("etl.reconcile.runningDisabled", { id: running })}
          </span>
        )}
      </div>
      <ConfirmDialog
        open={confirmRehash}
        onOpenChange={setConfirmRehash}
        title={t("etl.reconcile.rehashTitle")}
        text={t("etl.reconcile.rehashText")}
        confirm={t("etl.reconcile.rehashConfirm")}
        onConfirm={() => {
          setConfirmRehash(false);
          void act(() => etlApi.fullRehash(), () => t("etl.reconcile.started"));
        }}
      />

      <section className="space-y-2" data-testid="etl-reconcile-results">
        <h2 className="font-medium">{t("etl.reconcile.results")}</h2>
        {loading && !data ? (
          <Skeleton className="h-24 w-full" />
        ) : !data ? (
          <EmptyState text={t("etl.loadFailed")} />
        ) : data.items.length === 0 ? (
          <EmptyState text={t("etl.reconcile.none")} />
        ) : (
          <>
            <ScrollBox>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("etl.reconcile.columns.time")}</TableHead>
                    <TableHead>{t("etl.reconcile.columns.duration")}</TableHead>
                    <TableHead>{t("etl.reconcile.columns.kind")}</TableHead>
                    <TableHead>{t("etl.reconcile.columns.status")}</TableHead>
                    <TableHead className="text-right">{t("etl.reconcile.columns.gaps")}</TableHead>
                    <TableHead className="text-right">{t("etl.reconcile.columns.repaired")}</TableHead>
                    <TableHead className="text-right">{t("etl.reconcile.columns.reported")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((r) => {
                    const tot = levelTotals(r);
                    return (
                      <TableRow key={r.id} className="cursor-pointer" onClick={() => openReconcile(r.id)}>
                        <TableCell>
                          <button type="button" className="text-primary hover:underline">
                            <AbsTime value={r.started_at} />
                          </button>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {r.duration_seconds != null ? formatDuration(r.duration_seconds) : "--"}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {t(`etl.reconcile.kinds.${r.kind}`)}
                          {r.mode === "full_rehash" ? ` · ${t("etl.reconcile.modes.full_rehash")}` : ""}
                        </TableCell>
                        <TableCell className="min-w-[140px]">
                          <span className={cn(r.state === "incomplete" && "font-medium text-red-600")}>
                            {t(`etl.reconcile.states.${r.state}`)}
                          </span>
                          {r.reason && <div className="text-xs text-muted-foreground">{r.reason}</div>}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{tot.gaps}</TableCell>
                        <TableCell className="text-right tabular-nums">{tot.repaired}</TableCell>
                        <TableCell className="text-right tabular-nums">{tot.reported}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </ScrollBox>
            <Pager total={data.total} offset={offset} limit={RESULT_PAGE} onChange={setOffset} />
          </>
        )}
      </section>
    </div>
  );
}
