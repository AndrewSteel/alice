"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatDuration, formatNumber } from "@/i18n/format";
import { ReconcileGap, etlApi } from "@/services/etlApi";
import { AbsTime, EmptyState, Pager, useEtl, useEtlData } from "./EtlCommon";

const GAP_PAGE = 100;

/**
 * One reconciliation result (AK-32, AK-35): per level the gaps split into "repaired" and "reported
 * only", safeguard note, skipped folders, hash cycle. Gaps with a source id jump to the source
 * detail. There is deliberately no action on a single gap.
 */
export function EtlReconcileDetail({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Sheet open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl" data-testid="etl-reconcile-detail">
        <SheetHeader>
          <SheetTitle>{id !== null ? t("etl.reconcile.detail", { id }) : ""}</SheetTitle>
          <SheetDescription className="sr-only">{t("etl.reconcile.results")}</SheetDescription>
        </SheetHeader>
        {id !== null && <Body id={id} />}
      </SheetContent>
    </Sheet>
  );
}

function Body({ id }: { id: number }) {
  const { t } = useTranslation();
  const { data: r, loading, notFound } = useEtlData(() => etlApi.result(id), String(id), "rebuild");
  if (loading && !r) return <Skeleton className="mt-4 h-48 w-full" />;
  if (notFound) return <EmptyState text={t("etl.reconcile.none")} />;
  if (!r) return <EmptyState text={t("etl.loadFailed")} />;
  const s = r.summary ?? {};
  const levels = Object.keys(s.levels ?? {}).sort((a, b) => Number(a) - Number(b));
  const cycle = s.hash_cycle as { done?: number; total?: number; percent?: number; started_at?: string } | null | undefined;

  return (
    <div className="mt-4 space-y-4 text-sm">
      <p>
        <AbsTime value={r.started_at} />
        {r.duration_seconds != null && ` · ${formatDuration(r.duration_seconds)}`}
        {" · "}
        {t(`etl.reconcile.kinds.${r.kind}`)}
        {r.mode ? ` · ${t(`etl.reconcile.modes.${r.mode}`)}` : ""}
        {" · "}
        <strong>{t(`etl.reconcile.states.${r.state}`)}</strong>
      </p>
      {r.reason && <p className="text-muted-foreground">{r.reason}</p>}
      {r.guard_triggered && (
        <Alert variant="destructive" data-testid="etl-reconcile-guard">
          <AlertDescription>{t("etl.reconcile.guard")}</AlertDescription>
        </Alert>
      )}
      {(s.skipped_folders ?? []).length > 0 && (
        <section>
          <h3 className="font-medium">{t("etl.reconcile.skippedFolders")}</h3>
          <ul className="list-inside list-disc">
            {(s.skipped_folders ?? []).map((f, i) => (
              <li key={i} className="break-words [overflow-wrap:anywhere]">
                <span className="font-mono text-xs">{f.folder}</span> · {f.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      {cycle && (
        <section data-testid="etl-reconcile-hash-cycle">
          <h3 className="font-medium">{t("etl.reconcile.hashCycle")}</h3>
          <p>
            {t("etl.reconcile.hashCycleText", {
              done: formatNumber(cycle.done ?? 0),
              total: formatNumber(cycle.total ?? 0),
              percent: cycle.percent ?? 0,
              since: formatDate(cycle.started_at ?? null),
            })}
          </p>
        </section>
      )}
      {(s.notes ?? []).length > 0 && (
        <section>
          <h3 className="font-medium">{t("etl.reconcile.notes")}</h3>
          <ul className="list-inside list-disc">
            {(s.notes ?? []).map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </section>
      )}
      {Object.entries(s.gap_list_truncated ?? {}).map(([lv, n]) => (
        <p key={lv} className="text-muted-foreground">
          {t("etl.reconcile.truncated", { level: lv, n })}
        </p>
      ))}
      {levels.map((lv) => (
        <LevelGaps key={lv} resultId={id} level={Number(lv)} count={s.levels?.[lv]?.gaps ?? 0} />
      ))}
    </div>
  );
}

function LevelGaps({ resultId, level, count }: { resultId: number; level: number; count: number }) {
  const { t } = useTranslation();
  const [offset, setOffset] = useState(0);
  const { data, loading } = useEtlData(
    count > 0 ? () => etlApi.gaps(resultId, level, GAP_PAGE, offset) : null,
    `${resultId}/${level}/${offset}`,
    "rebuild"
  );
  const items = (data?.items ?? []).filter((g) => g.gap !== "folder_skipped");
  const repaired = items.filter((g) => g.action === "repaired");
  const reported = items.filter((g) => g.action !== "repaired");
  return (
    <section className="space-y-2 rounded-md border p-2" data-testid={`etl-level-${level}`}>
      <h3 className="font-medium">
        {t("etl.reconcile.level", { n: level })} · {count}
      </h3>
      {count === 0 ? (
        <p className="text-muted-foreground">{t("etl.reconcile.noGaps")}</p>
      ) : loading && !data ? (
        <Skeleton className="h-12 w-full" />
      ) : (
        <>
          <GapList title={t("etl.reconcile.repaired")} gaps={repaired} />
          <GapList title={t("etl.reconcile.reported")} gaps={reported} />
          {data && <Pager total={data.total} offset={offset} limit={GAP_PAGE} onChange={setOffset} />}
        </>
      )}
    </section>
  );
}

function GapList({ title, gaps }: { title: string; gaps: ReconcileGap[] }) {
  const { t } = useTranslation();
  const { openSource } = useEtl();
  if (gaps.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-medium uppercase text-muted-foreground">{title}</h4>
      <ul className="space-y-1">
        {gaps.map((g, i) => (
          <li key={i} className="border-b pb-1 last:border-0">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono">{g.gap}</span>
              {g.action === "repair_failed" && <span className="text-red-600">{t("etl.reconcile.repairFailed")}</span>}
              {g.source_id && (
                <button type="button" className="font-mono text-primary hover:underline" onClick={() => openSource(g.source_id as string)}>
                  {g.source_id}
                </button>
              )}
            </div>
            {g.path && <p className="break-words font-mono text-xs [overflow-wrap:anywhere]">{g.path}</p>}
            {g.detail && <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">{g.detail}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
