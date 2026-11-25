"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/i18n/format";
import { cn } from "@/lib/utils";
import { ETL_KINDS, ETL_STATES, EtlState } from "@/services/etlApi";
import { EmptyState, FilterSelect, ScrollBox, useEtl } from "./EtlCommon";
import { EtlSourceList } from "./EtlSourceList";

interface EtlOverviewProps {
  kind: string;
  onKind: (k: string) => void;
  includeDeleted: boolean;
  onIncludeDeleted: (v: boolean) => void;
}

/** Matrix stage × state (AK-5–7); a click on a cell opens the filtered source list (AK-8). */
export function EtlOverview({ kind, onKind, includeDeleted, onIncludeDeleted }: EtlOverviewProps) {
  const { t } = useTranslation();
  const { state } = useEtl();
  const [cell, setCell] = useState<{ stage: string; state: EtlState } | null>(null);
  if (!state) return null;

  const total = state.stages.reduce(
    (n, st) => n + Object.values(state.matrix[st] ?? {}).reduce((a, b) => a + b, 0),
    0
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect
          label={t("etl.filters.kind")}
          value={kind}
          onChange={onKind}
          allLabel={t("etl.filters.allKinds")}
          options={ETL_KINDS.map((k) => ({ value: k, label: t(`etl.kinds.${k}`) }))}
        />
        <div className="flex items-center gap-2">
          <Checkbox
            id="etl-show-deleted"
            checked={includeDeleted}
            onCheckedChange={(v) => onIncludeDeleted(v === true)}
          />
          <Label htmlFor="etl-show-deleted" className="text-sm font-normal">
            {t("etl.filters.showDeleted")}
          </Label>
        </div>
      </div>

      {total === 0 ? (
        <EmptyState text={kind ? t("etl.matrix.emptyKind") : t("etl.matrix.empty")} />
      ) : (
        <ScrollBox>
          <Table data-testid="etl-matrix">
            <caption className="sr-only">{t("etl.matrix.title")}</caption>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-card">{t("etl.matrix.stage")}</TableHead>
                {ETL_STATES.map((s) => (
                  <TableHead key={s} className="whitespace-nowrap text-right">
                    {t(`etl.states.${s}`)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.stages.map((stage) => (
                <TableRow key={stage}>
                  <TableCell className="sticky left-0 bg-card font-medium">{stage}</TableCell>
                  {ETL_STATES.map((s) => {
                    const n = state.matrix[stage]?.[s] ?? 0;
                    const active = cell?.stage === stage && cell.state === s;
                    return (
                      <TableCell key={s} className="p-1 text-right">
                        <button
                          type="button"
                          data-stage={stage}
                          data-state={s}
                          onClick={() => setCell({ stage, state: s })}
                          aria-label={t("etl.matrix.cellAria", { n, stage, state: t(`etl.states.${s}`) })}
                          className={cn(
                            "min-w-[3rem] rounded px-2 py-1 tabular-nums hover:bg-accent",
                            n === 0 && "text-muted-foreground",
                            (s === "failed_permanent" || s === "failed") && n > 0 && "font-semibold text-red-600",
                            active && "bg-accent ring-2 ring-primary"
                          )}
                        >
                          {formatNumber(n)}
                        </button>
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollBox>
      )}

      {cell ? (
        <EtlSourceList
          key={`${cell.stage}/${cell.state}/${kind}/${includeDeleted}`}
          stage={cell.stage}
          state={cell.state}
          kind={kind}
          deleted={includeDeleted ? "all" : "no"}
          onClose={() => setCell(null)}
        />
      ) : (
        total > 0 && <p className="text-sm text-muted-foreground">{t("etl.list.hint")}</p>
      )}
    </div>
  );
}
