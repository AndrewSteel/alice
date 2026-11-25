"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/i18n/format";
import { ErrorFilter, SourceFilter, etlApi } from "@/services/etlApi";
import { ConfirmDialog, useEtl, useEtlAction } from "./EtlCommon";

interface EtlBulkRetryProps {
  scope: "sources" | "errors";
  filter: SourceFilter | ErrorFilter;
  /** Number of sources a bulk retry would hit, as delivered with the list. */
  retryable: number;
}

/**
 * "Retry all N" for the current selection (AK-16–18). The dialog shows the number counted at
 * opening time; the server re-evaluates the selection on execution (EC-2) and enforces the limit.
 */
export function EtlBulkRetry({ scope, filter, retryable }: EtlBulkRetryProps) {
  const { t } = useTranslation();
  const { state, registerDown, goTo } = useEtl();
  const act = useEtlAction();
  const [count, setCount] = useState<number | null>(null);
  const limit = state?.retry_limit ?? 1000;

  if (retryable === 0) return null;

  if (retryable > limit) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-yellow-500 bg-yellow-500/10 p-2 text-sm">
        <span>{t("etl.bulk.limitHint", { limit: formatNumber(limit) })}</span>
        <Button size="sm" variant="outline" onClick={() => goTo("rebuild")}>
          {t("etl.bulk.toRebuild")}
        </Button>
      </div>
    );
  }

  const open = async () => {
    const r = await act(() => etlApi.bulkRetry(scope, filter, true));
    if (r) setCount(r.sources);
  };

  return (
    <>
      <Button size="sm" variant="secondary" disabled={registerDown} onClick={open} data-testid="etl-bulk-retry">
        {t("etl.bulk.button", { n: formatNumber(retryable) })}
      </Button>
      <ConfirmDialog
        open={count !== null}
        onOpenChange={(o) => !o && setCount(null)}
        title={t("etl.bulk.confirmTitle")}
        text={t("etl.bulk.confirmText", { n: formatNumber(count ?? 0) })}
        confirm={t("etl.bulk.confirm")}
        onConfirm={() => {
          setCount(null);
          void act(
            () => etlApi.bulkRetry(scope, filter, false),
            (r) => t("etl.bulk.done", { n: formatNumber(r.sources) })
          );
        }}
      />
    </>
  );
}
