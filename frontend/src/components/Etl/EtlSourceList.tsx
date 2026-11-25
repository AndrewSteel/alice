"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ETL_KINDS, ETL_STATES, EtlState, SourceFilter, etlApi } from "@/services/etlApi";
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

interface EtlSourceListProps {
  stage: string;
  state: EtlState;
  kind: string;
  deleted: "no" | "all";
  onClose: () => void;
}

/** Sources of one matrix cell, paged, with further filters and search (AK-8–10). */
export function EtlSourceList({ stage, state, kind: initialKind, deleted: initialDeleted, onClose }: EtlSourceListProps) {
  const { t } = useTranslation();
  const { openSource } = useEtl();
  const [st, setSt] = useState<string>(state);
  const [kind, setKind] = useState(initialKind);
  const [deleted, setDeleted] = useState<string>(initialDeleted);
  const [locked, setLocked] = useState<string>("all");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setQ(qInput.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(id);
  }, [qInput]);

  const filter: SourceFilter = {
    stage,
    state: st as EtlState | "",
    kind: kind as SourceFilter["kind"],
    deleted: deleted as SourceFilter["deleted"],
    locked: locked as SourceFilter["locked"],
    q,
  };
  const key = JSON.stringify([filter, offset]);
  const { data, loading } = useEtlData(() => etlApi.sources(filter, PAGE_SIZE, offset), key, "register");
  const set = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setOffset(0);
  };

  return (
    <section className="space-y-2 rounded-md border p-2 sm:p-3" aria-labelledby="etl-list-title" data-testid="etl-source-list">
      <div className="flex items-start justify-between gap-2">
        <h2 id="etl-list-title" className="font-medium">
          {st ? t("etl.list.titleState", { stage, state: t(`etl.states.${st}`) }) : t("etl.list.title", { stage })}
        </h2>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label={t("etl.list.close")}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <FilterSelect
          label={t("etl.filters.state")}
          value={st}
          onChange={set(setSt)}
          allLabel={t("etl.filters.allStates")}
          options={ETL_STATES.map((s) => ({ value: s, label: t(`etl.states.${s}`) }))}
        />
        <FilterSelect
          label={t("etl.filters.kind")}
          value={kind}
          onChange={set(setKind)}
          allLabel={t("etl.filters.allKinds")}
          options={ETL_KINDS.map((k) => ({ value: k, label: t(`etl.kinds.${k}`) }))}
        />
        <FilterSelect
          label={t("etl.filters.deleted")}
          value={deleted}
          onChange={set((v: string) => setDeleted(v || "no"))}
          options={[
            { value: "no", label: t("etl.filters.deletedNo") },
            { value: "yes", label: t("etl.filters.deletedYes") },
            { value: "all", label: t("etl.filters.deletedAll") },
          ]}
        />
        <FilterSelect
          label={t("etl.filters.locked")}
          value={locked}
          onChange={set((v: string) => setLocked(v || "all"))}
          options={[
            { value: "all", label: t("etl.filters.lockedAll") },
            { value: "yes", label: t("etl.filters.lockedYes") },
            { value: "no", label: t("etl.filters.lockedNo") },
          ]}
        />
        <Input
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder={t("etl.filters.search")}
          aria-label={t("etl.filters.searchAria")}
          className="h-8 w-full text-xs sm:w-[220px]"
          maxLength={200}
        />
      </div>

      {data && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="text-muted-foreground">{t("etl.list.total", { n: data.total })}</span>
          <EtlBulkRetry scope="sources" filter={filter} retryable={data.retryable ?? 0} />
        </div>
      )}

      {loading && !data ? (
        <Skeleton className="h-32 w-full" />
      ) : !data ? (
        <EmptyState text={t("etl.loadFailed")} />
      ) : data.items.length === 0 ? (
        <EmptyState text={t("etl.list.empty")} />
      ) : (
        <>
          <ScrollBox>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("etl.list.columns.title")}</TableHead>
                  <TableHead>{t("etl.list.columns.kind")}</TableHead>
                  <TableHead>{t("etl.list.columns.state")}</TableHead>
                  <TableHead className="text-right">{t("etl.list.columns.attempts")}</TableHead>
                  <TableHead>{t("etl.list.columns.error")}</TableHead>
                  <TableHead>{t("etl.list.columns.lastAttempt")}</TableHead>
                  <TableHead>{t("etl.list.columns.nextRetry")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((it) => (
                  <TableRow key={`${it.id}/${it.stage}`}>
                    <TableCell className="min-w-[180px] max-w-[320px]">
                      <button
                        type="button"
                        className="text-left text-primary hover:underline"
                        onClick={() => openSource(it.id)}
                      >
                        <SourceTitle title={it.title} id={it.id} />
                      </button>
                      <div className="flex flex-wrap gap-1 pt-0.5 font-mono text-[11px] text-muted-foreground">
                        {it.id}
                        {it.deleted && <Badge variant="outline">{t("etl.list.deletedBadge")}</Badge>}
                        {it.locked && <Badge variant="destructive">{t("etl.list.lockedBadge")}</Badge>}
                      </div>
                    </TableCell>
                    <TableCell>{t(`etl.kinds.${it.kind}`)}</TableCell>
                    <TableCell>
                      <StateBadge state={it.state} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{it.attempts}</TableCell>
                    <TableCell className="min-w-[200px] max-w-[360px] text-xs">
                      <span className="line-clamp-2 break-words [overflow-wrap:anywhere]">
                        {it.error ? `${it.error}${it.error_truncated ? "…" : ""}` : ""}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">
                      <RelTime value={it.last_attempt_at} />
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
