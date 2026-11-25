"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDuration, formatNumber } from "@/i18n/format";
import { ETL_KINDS, RebuildPreview, RebuildProgress, etlApi } from "@/services/etlApi";
import {
  AbsTime,
  ConfirmDialog,
  EmptyState,
  FilterSelect,
  PAGE_SIZE,
  Pager,
  RelTime,
  ScrollBox,
  SourceTitle,
  useEtl,
  useEtlAction,
  useEtlData,
} from "./EtlCommon";

const ACTIVE = ["running", "paused", "waiting"];

/** Rebuild: start with preview, running run with progress and controls, its errors, history (AK-20–29). */
export function EtlRebuild() {
  const { t } = useTranslation();
  const { state, rebuildDown } = useEtl();
  const [startOpen, setStartOpen] = useState(false);
  const [errorsRun, setErrorsRun] = useState<number | null>(null);
  const reb = state?.rebuild;
  const run = reb?.run ?? null;
  const active = !!(reb?.active && run);
  const shownErrorsRun = errorsRun ?? run?.id ?? null;

  if (reb === null || reb === undefined) {
    return <EmptyState text={t("etl.unavailableRebuild")} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setStartOpen(true)} disabled={active || rebuildDown} data-testid="etl-rebuild-start">
          {t("etl.rebuild.start")}
        </Button>
        {active && run && (
          <span className="text-sm text-muted-foreground" data-testid="etl-rebuild-start-reason">
            {t("etl.rebuild.startDisabled", { id: run.id, status: t(`etl.runStatus.${run.status}`) })}
          </span>
        )}
      </div>

      <section className="space-y-2">
        <h2 className="font-medium">{t("etl.rebuild.current")}</h2>
        {!run ? (
          <EmptyState text={t("etl.rebuild.none")} />
        ) : !active ? (
          <EmptyState text={t("etl.rebuild.noActive")} />
        ) : (
          <RunProgress run={run} />
        )}
      </section>

      {shownErrorsRun !== null && <RunErrors runId={shownErrorsRun} />}

      <History onShowErrors={setErrorsRun} />

      {startOpen && <StartDialog onClose={() => setStartOpen(false)} />}
    </div>
  );
}

function StageBar({ stage, v }: { stage: string; v: { sources: number; done: number; failed: number; running: number; open: number } }) {
  const { t } = useTranslation();
  const total = Math.max(1, v.sources);
  const parts = [
    { n: v.done, cls: "fill-green-500" },
    { n: v.failed, cls: "fill-red-500" },
    { n: v.running, cls: "fill-blue-500" },
    { n: v.open, cls: "fill-muted-foreground/30" },
  ];
  let x = 0;
  return (
    <div className="space-y-0.5" data-testid={`etl-bar-${stage}`}>
      <div className="flex flex-wrap justify-between gap-x-2 text-xs">
        <span className="font-medium">{stage}</span>
        <span className="tabular-nums text-muted-foreground">
          {v.done} · {v.failed} · {v.running} · {v.open}
        </span>
      </div>
      <svg
        viewBox="0 0 100 4"
        preserveAspectRatio="none"
        className="h-2 w-full rounded bg-muted"
        role="img"
        aria-label={t("etl.rebuild.barAria", { stage, ...v })}
      >
        {parts.map((p, i) => {
          const w = (p.n / total) * 100;
          const r = <rect key={i} x={x} y={0} width={w} height={4} className={p.cls} />;
          x += w;
          return r;
        })}
      </svg>
    </div>
  );
}

function RunProgress({ run }: { run: RebuildProgress }) {
  const { t } = useTranslation();
  const { rebuildDown } = useEtl();
  const act = useEtlAction();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const excluded = Object.entries(run.excluded ?? {});
  const rest = run.remaining_seconds;
  const unknown = rest === null || rest === undefined || !run.throughput_per_hour;

  return (
    <div className="space-y-3 rounded-md border p-3" data-testid="etl-rebuild-run">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t("etl.rebuild.run", { id: run.id })}</span>
        <span className="rounded bg-accent px-2 py-0.5 text-sm" data-testid="etl-rebuild-status">
          {t(`etl.runStatus.${run.status}`)}
        </span>
        {run.reason && (
          <span className="text-sm text-muted-foreground" data-testid="etl-rebuild-reason">
            {t("etl.rebuild.reason")}: {run.reason}
          </span>
        )}
      </div>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        <Item label={t("etl.rebuild.scope")}>
          {t("etl.rebuild.scopeText", {
            stage: run.start_stage,
            kind: run.kind ? t(`etl.kinds.${run.kind}`) : t("etl.rebuild.allKinds"),
          })}
        </Item>
        <Item label={t("etl.rebuild.startedAt")}>
          <AbsTime value={run.started_at} />
        </Item>
        <Item label={t("etl.rebuild.startedBy")}>{run.started_by}</Item>
        <Item label={t("etl.rebuild.total")}>{formatNumber(run.total)}</Item>
        <Item label={t("etl.rebuild.excluded")}>
          {excluded.length === 0
            ? t("etl.rebuild.excludedNone")
            : excluded.map(([k, n]) => `${t(`etl.excludedReasons.${k}`, { defaultValue: k })} ${formatNumber(n)}`).join(" · ")}
        </Item>
        <Item label={t("etl.rebuild.throughput")}>{t("etl.rebuild.perHour", { n: formatNumber(run.throughput_per_hour ?? 0) })}</Item>
        <Item label={t("etl.rebuild.remaining")}>
          <span data-testid="etl-rebuild-remaining">{unknown ? t("etl.rebuild.unknown") : formatDuration(rest as number)}</span>
        </Item>
        <Item label={t("etl.rebuild.asOf")}>
          <RelTime value={run.as_of} />
        </Item>
      </dl>
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">{t("etl.rebuild.barLegend")}</p>
        {Object.entries(run.stages ?? {}).map(([st, v]) => (
          <StageBar key={st} stage={st} v={v} />
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {(run.status === "running" || run.status === "waiting") && (
          <Button size="sm" variant="outline" disabled={rebuildDown} onClick={() => act(() => etlApi.control(run.id, "pause"))}>
            {t("etl.rebuild.pause")}
          </Button>
        )}
        {run.status === "paused" && (
          <Button size="sm" variant="outline" disabled={rebuildDown} onClick={() => act(() => etlApi.control(run.id, "resume"))}>
            {t("etl.rebuild.resume")}
          </Button>
        )}
        {ACTIVE.includes(run.status) && (
          <Button size="sm" variant="destructive" disabled={rebuildDown} onClick={() => setConfirmCancel(true)}>
            {t("etl.rebuild.cancel")}
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirmCancel}
        onOpenChange={setConfirmCancel}
        title={t("etl.rebuild.cancelTitle")}
        text={t("etl.rebuild.cancelText")}
        confirm={t("etl.rebuild.cancelConfirm")}
        cancel={t("etl.rebuild.keepRunning")}
        destructive
        onConfirm={() => {
          setConfirmCancel(false);
          void act(() => etlApi.control(run.id, "cancel"));
        }}
      />
    </div>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground">{label}:</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function RunErrors({ runId }: { runId: number }) {
  const { t } = useTranslation();
  const { openSource } = useEtl();
  const [offset, setOffset] = useState(0);
  const { data, loading } = useEtlData(
    () => etlApi.runErrors(runId, PAGE_SIZE, offset),
    `${runId}/${offset}`,
    "rebuild"
  );
  return (
    <section className="space-y-2" data-testid="etl-run-errors">
      <h2 className="font-medium">
        {t("etl.rebuild.errors")} · {t("etl.rebuild.run", { id: runId })}
      </h2>
      {loading && !data ? (
        <Skeleton className="h-16 w-full" />
      ) : !data ? (
        <EmptyState text={t("etl.loadFailed")} />
      ) : data.items.length === 0 ? (
        <EmptyState text={t("etl.rebuild.noErrors")} />
      ) : (
        <>
          <ScrollBox>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("etl.detail.id")}</TableHead>
                  <TableHead>{t("etl.list.columns.title")}</TableHead>
                  <TableHead>{t("etl.list.columns.stage")}</TableHead>
                  <TableHead>{t("etl.list.columns.error")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((e) => (
                  <TableRow key={`${e.id}/${e.stage}`}>
                    <TableCell>
                      <button type="button" className="font-mono text-xs text-primary hover:underline" onClick={() => openSource(e.id)}>
                        {e.id}
                      </button>
                    </TableCell>
                    <TableCell className="min-w-[160px] max-w-[280px]">
                      <SourceTitle title={e.title} id={e.id} />
                    </TableCell>
                    <TableCell>{e.stage}</TableCell>
                    <TableCell className="min-w-[200px] max-w-[360px] text-xs">
                      <span className="line-clamp-3 break-words [overflow-wrap:anywhere]">{e.error}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollBox>
          <Pager total={data.total} offset={offset} limit={PAGE_SIZE} onChange={setOffset} />
        </>
      )}
    </section>
  );
}

function History({ onShowErrors }: { onShowErrors: (id: number) => void }) {
  const { t } = useTranslation();
  const { openReconcile } = useEtl();
  const [offset, setOffset] = useState(0);
  const { data, loading } = useEtlData(() => etlApi.rebuilds(20, offset), String(offset), "rebuild");
  const items = (data?.items ?? []).filter((r) => r.status === "done" || r.status === "cancelled");
  return (
    <section className="space-y-2" data-testid="etl-rebuild-history">
      <h2 className="font-medium">{t("etl.rebuild.history")}</h2>
      {loading && !data ? (
        <Skeleton className="h-16 w-full" />
      ) : !data ? (
        <EmptyState text={t("etl.loadFailed")} />
      ) : items.length === 0 ? (
        <EmptyState text={offset === 0 && data.total === 0 ? t("etl.rebuild.none") : t("etl.rebuild.noHistory")} />
      ) : (
        <>
          <ScrollBox>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("etl.rebuild.columns.run")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.status")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.scope")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.time")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.startedBy")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.counts")}</TableHead>
                  <TableHead>{t("etl.rebuild.columns.reconcile")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <button type="button" className="text-primary hover:underline" onClick={() => onShowErrors(r.id)}>
                        {r.id}
                      </button>
                    </TableCell>
                    <TableCell>{t(`etl.runStatus.${r.status}`)}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      {t("etl.rebuild.scopeText", {
                        stage: r.start_stage,
                        kind: r.kind ? t(`etl.kinds.${r.kind}`) : t("etl.rebuild.allKinds"),
                      })}
                    </TableCell>
                    <TableCell className="text-xs">
                      <AbsTime value={r.started_at} /> – <AbsTime value={r.finished_at} />
                    </TableCell>
                    <TableCell>{r.started_by}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {t("etl.rebuild.finalCounts", { finished: r.finished ?? 0, in_run: r.in_run ?? 0 })}
                    </TableCell>
                    <TableCell>
                      {r.reconcile_id ? (
                        <button
                          type="button"
                          className="whitespace-nowrap text-primary hover:underline"
                          onClick={() => openReconcile(r.reconcile_id as number)}
                        >
                          {t("etl.rebuild.reconcileLink", { id: r.reconcile_id })}
                        </button>
                      ) : (
                        "--"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollBox>
          <Pager total={data.total} offset={offset} limit={20} onChange={setOffset} />
        </>
      )}
    </section>
  );
}

function StartDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { state } = useEtl();
  const act = useEtlAction();
  const stages = (state?.stages ?? []).filter((s, i) => i > 0 && s !== "detect"); // AK-20
  const [stage, setStage] = useState(stages[0] ?? "");
  const [kind, setKind] = useState("");
  const [preview, setPreview] = useState<RebuildPreview | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!stage) return;
    let cancelled = false;
    setPreview(null);
    etlApi
      .preview(stage, kind || undefined)
      .then((p) => !cancelled && setPreview(p))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [stage, kind]);

  const start = async () => {
    setBusy(true);
    const r = await act(() => etlApi.startRebuild(stage, kind || undefined), () => t("etl.rebuild.started"));
    setBusy(false);
    if (r) onClose();
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-[calc(100vw-2rem)] sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("etl.rebuild.startTitle")}</DialogTitle>
          <DialogDescription className="sr-only">{t("etl.rebuild.startTitle")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>{t("etl.rebuild.startStage")}</Label>
            <FilterSelect
              label={t("etl.rebuild.startStage")}
              value={stage}
              onChange={(v) => v && setStage(v)}
              options={stages.map((s) => ({ value: s, label: s }))}
              className="w-full"
            />
          </div>
          <div className="space-y-1">
            <Label>{t("etl.rebuild.kind")}</Label>
            <FilterSelect
              label={t("etl.rebuild.kind")}
              value={kind}
              onChange={setKind}
              allLabel={t("etl.rebuild.allKinds")}
              options={ETL_KINDS.map((k) => ({ value: k, label: t(`etl.kinds.${k}`) }))}
              className="w-full"
            />
          </div>
          <p className="text-sm" data-testid="etl-rebuild-preview">
            {preview
              ? t("etl.rebuild.preview", { n: formatNumber(preview.sources), stages: preview.stages.join(", ") })
              : t("etl.rebuild.previewLoading")}
          </p>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={start} disabled={!preview || busy}>
            {t("etl.rebuild.confirmStart")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
