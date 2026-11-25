"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ETL_KINDS, ErrorFilter, etlApi } from "@/services/etlApi";
import { EtlBulkRetry } from "./EtlBulkRetry";
import {
  EmptyState,
  FilterSelect,
  PAGE_SIZE,
  Pager,
  RelTime,
  ScrollBox,
  SourceTitle,
  StateBadge,
  useEtl,
  useEtlData,
} from "./EtlCommon";

/** All failed stages and locked sources, newest error first, with filters (AK-11). */
export function EtlErrors() {
  const { t } = useTranslation();
  const { state, openSource } = useEtl();
  const [stage, setStage] = useState("");
  const [st, setSt] = useState("");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const filter: ErrorFilter = { stage, state: st as ErrorFilter["state"], kind: kind as ErrorFilter["kind"] };
  const { data, loading } = useEtlData(
    () => etlApi.errors(filter, PAGE_SIZE, offset),
    JSON.stringify([filter, offset]),
    "register"
  );
  const set = (fn: (v: string) => void) => (v: string) => {
    fn(v);
    setOffset(0);
  };

  return (
    <section className="space-y-2" data-testid="etl-errors">
      <div className="flex flex-wrap gap-2">
        <FilterSelect
          label={t("etl.filters.stage")}
          value={stage}
          onChange={set(setStage)}
          allLabel={t("etl.filters.allStages")}
          options={(state?.stages ?? []).map((s) => ({ value: s, label: s }))}
        />
        <FilterSelect
          label={t("etl.filters.state")}
          value={st}
          onChange={set(setSt)}
          allLabel={t("etl.filters.allStates")}
          options={(["failed", "failed_permanent", "locked"] as const).map((s) => ({
            value: s,
            label: t(`etl.states.${s}`),
          }))}
        />
        <FilterSelect
          label={t("etl.filters.kind")}
          value={kind}
          onChange={set(setKind)}
          allLabel={t("etl.filters.allKinds")}
          options={ETL_KINDS.map((k) => ({ value: k, label: t(`etl.kinds.${k}`) }))}
        />
      </div>

      {data && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="text-muted-foreground">{t("etl.list.total", { n: data.total })}</span>
          <EtlBulkRetry scope="errors" filter={filter} retryable={data.retryable ?? 0} />
        </div>
      )}

      {loading && !data ? (
        <Skeleton className="h-32 w-full" />
      ) : !data ? (
        <EmptyState text={t("etl.loadFailed")} />
      ) : data.items.length === 0 ? (
        <EmptyState text={t("etl.errors.empty")} />
      ) : (
        <>
          <ScrollBox>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("etl.list.columns.title")}</TableHead>
                  <TableHead>{t("etl.list.columns.kind")}</TableHead>
                  <TableHead>{t("etl.list.columns.stage")}</TableHead>
                  <TableHead>{t("etl.list.columns.state")}</TableHead>
                  <TableHead className="text-right">{t("etl.list.columns.attempts")}</TableHead>
                  <TableHead>{t("etl.list.columns.error")}</TableHead>
                  <TableHead>{t("etl.list.columns.errorAt")}</TableHead>
                  <TableHead>{t("etl.list.columns.nextRetry")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((it) => (
                  <TableRow key={`${it.id}/${it.stage ?? "lock"}`}>
                    <TableCell className="min-w-[180px] max-w-[320px]">
                      <button type="button" className="text-left text-primary hover:underline" onClick={() => openSource(it.id)}>
                        <SourceTitle title={it.title} id={it.id} />
                      </button>
                      <div className="font-mono text-[11px] text-muted-foreground">{it.id}</div>
                    </TableCell>
                    <TableCell>{t(`etl.kinds.${it.kind}`)}</TableCell>
                    <TableCell>{it.stage ?? t("etl.errors.lockedStage")}</TableCell>
                    <TableCell>
                      <StateBadge state={it.state} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{it.attempts ?? ""}</TableCell>
                    <TableCell className="min-w-[200px] max-w-[360px] text-xs">
                      <span className="line-clamp-2 break-words [overflow-wrap:anywhere]">
                        {it.error ? `${it.error}${it.error_truncated ? "…" : ""}` : ""}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">
                      <RelTime value={it.error_at} />
                    </TableCell>
                    <TableCell className="text-xs">
                      <RelTime value={it.next_retry_at} />
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
