"use client";

import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { etlApi } from "@/services/etlApi";
import { AbsTime, EmptyState, RelTime, SourceTitle, StateBadge, useEtl, useEtlAction, useEtlData } from "./EtlCommon";

/** Everything about one source (AK-12) with "retry" per failed stage (AK-13–15, AK-19, EC-1, EC-3). */
export function EtlSourceDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Sheet open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl" data-testid="etl-source-detail">
        <SheetHeader>
          <SheetTitle>{t("etl.detail.title")}</SheetTitle>
          <SheetDescription className="font-mono text-xs">{id}</SheetDescription>
        </SheetHeader>
        {id && <DetailBody id={id} />}
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function DetailBody({ id }: { id: string }) {
  const { t } = useTranslation();
  const { registerDown } = useEtl();
  const act = useEtlAction();
  const { data: d, loading, notFound } = useEtlData(() => etlApi.source(id), id, "register");

  if (loading && !d) return <Skeleton className="mt-4 h-64 w-full" />;
  if (notFound) return <EmptyState text={t("etl.detail.notFound")} />;
  if (!d) return <EmptyState text={t("etl.loadFailed")} />;

  return (
    <div className="mt-4 space-y-5">
      <h3 className="text-lg font-semibold">
        <SourceTitle title={d.title} id={d.id} />
      </h3>
      <dl className="space-y-1">
        <Field label={t("etl.detail.id")}>
          <span className="font-mono">{d.id}</span>
        </Field>
        <Field label={t("etl.detail.kind")}>{t(`etl.kinds.${d.kind}`)}</Field>
        <Field label={t("etl.detail.type")}>{d.type ?? "--"}</Field>
        <Field label={t("etl.detail.hash")}>
          <span className="font-mono text-xs">{d.hash}</span>
        </Field>
        <Field label={t("etl.detail.deleted")}>
          {d.deleted ? t("etl.detail.yes") : t("etl.detail.no")}
          {d.deleted_at && (
            <>
              {" · "}
              <AbsTime value={d.deleted_at} />
            </>
          )}
        </Field>
        <Field label={t("etl.detail.path")}>
          <span className="font-mono text-xs">{d.path}</span>
        </Field>
      </dl>

      {d.locked && (
        <Alert variant="destructive" data-testid="etl-detail-lock">
          <AlertTitle>{t("etl.detail.lock")}</AlertTitle>
          <AlertDescription className="space-y-1">
            <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{d.repo_error}</p>
            <p>{t("etl.detail.lockHint")}</p>
          </AlertDescription>
        </Alert>
      )}
      {d.deleted && <p className="text-sm text-muted-foreground">{t("etl.detail.deletedHint")}</p>}

      <section className="space-y-2">
        <h4 className="font-medium">{t("etl.detail.stages")}</h4>
        <ul className="space-y-2">
          {d.stages.map((s) => (
            <li key={s.stage} className="space-y-1 rounded-md border p-2" data-stage={s.stage}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{s.stage}</span>
                <StateBadge state={s.state} />
                <span className="text-xs text-muted-foreground">{t("etl.detail.attempts", { n: s.attempts })}</span>
                {s.retryable && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="ml-auto h-7"
                    disabled={registerDown}
                    onClick={() =>
                      act(() => etlApi.retry(d.id, s.stage), () => t("etl.detail.retried", { stage: s.stage }))
                    }
                  >
                    {t("etl.detail.retry")}
                  </Button>
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
                <span>
                  {t("etl.detail.lastAttempt")}: <AbsTime value={s.last_attempt_at} />
                </span>
                {s.next_retry_at && (
                  <span>
                    {t("etl.detail.nextRetry")}: <RelTime value={s.next_retry_at} />
                  </span>
                )}
              </div>
              {s.error && (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs [overflow-wrap:anywhere]">
                  {s.error}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h4 className="font-medium">{t("etl.detail.locations")}</h4>
        {d.locations.length === 0 ? (
          <EmptyState text={t("etl.detail.noLocations")} />
        ) : (
          <ul className="space-y-1 text-sm">
            {d.locations.map((l, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge variant={l.present ? "secondary" : "outline"}>
                  {l.present ? t("etl.detail.present") : t("etl.detail.gone")}
                </Badge>
                <span className="min-w-0 break-words font-mono text-xs [overflow-wrap:anywhere]">
                  {l.path ?? `${l.mailbox} · ${l.message_id}`}
                </span>
                {l.gone_at && (
                  <span className="text-xs text-muted-foreground">
                    <AbsTime value={l.gone_at} />
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="font-medium">{t("etl.detail.events")}</h4>
        {d.events.length === 0 ? (
          <EmptyState text={t("etl.detail.noEvents")} />
        ) : (
          <ul className="space-y-1 text-sm">
            {d.events.map((e, i) => (
              <li key={i} className="border-b pb-1 last:border-0">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <AbsTime value={e.created_at} />
                  <span className="font-mono">{e.event}</span>
                  {e.level !== "info" && <Badge variant={e.level === "error" ? "destructive" : "outline"}>{e.level}</Badge>}
                </div>
                <p className="break-words [overflow-wrap:anywhere]">{e.message}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
