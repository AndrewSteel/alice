"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { formatDateTimeShort, formatRelative } from "@/i18n/format";
import { cn } from "@/lib/utils";
import { EtlError, EtlStateResponse } from "@/services/etlApi";

export const ALL = "__all__";
export const PAGE_SIZE = 50;

/** Shared state of the ETL page (PROJ-122): refresh tick, service availability, navigation. */
export interface EtlContextValue {
  tick: number;
  state: EtlStateResponse | null;
  registerDown: boolean;
  rebuildDown: boolean;
  /** Report the outcome of a background load: drives the banners, never a toast (AK-41). */
  report: (service: "register" | "rebuild", ok: boolean) => void;
  reload: () => void;
  openSource: (id: string) => void;
  openReconcile: (id: number) => void;
  goTo: (tab: "overview" | "errors" | "rebuild" | "reconcile") => void;
}

export const EtlContext = createContext<EtlContextValue | null>(null);

export function useEtl(): EtlContextValue {
  const ctx = useContext(EtlContext);
  if (!ctx) throw new Error("useEtl outside EtlContext");
  return ctx;
}

/** Runs a user action; on rejection a toast shows the reason (AK-42); afterwards the view reloads. */
export function useEtlAction() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { reload } = useEtl();
  return useCallback(
    async <T,>(fn: () => Promise<T>, success?: (r: T) => string | undefined): Promise<T | undefined> => {
      try {
        const r = await fn();
        const msg = success?.(r);
        if (msg) toast({ title: msg });
        return r;
      } catch (e) {
        toast({ title: t("etl.toast.failed"), description: describeError(e, t), variant: "destructive" });
        return undefined;
      } finally {
        reload();
      }
    },
    [t, toast, reload]
  );
}

type TFn = (key: string, opts?: Record<string, unknown>) => string;

export function describeError(e: unknown, t: TFn): string {
  if (!(e instanceof EtlError)) return e instanceof Error ? e.message : t("common.unknownError");
  if (e.status === 0) return t("etl.toast.network");
  if (e.code === "service_unavailable") return t("etl.toast.unavailable");
  if (e.code === "limit_exceeded")
    return t("etl.bulk.limitExceeded", { count: e.body.count as number, limit: e.body.limit as number });
  if (e.code === "not_retryable") {
    if (e.body.reason === "locked") return t("etl.toast.notRetryableLocked");
    if (e.body.reason === "deleted") return t("etl.toast.notRetryableDeleted");
    return t("etl.toast.notRetryableState", { state: t(`etl.states.${String(e.body.state)}`) });
  }
  return e.message; // reasons of the register / PROJ-120 unchanged
}

export function StateBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  const cls: Record<string, string> = {
    done: "bg-green-500/15 text-green-700 dark:text-green-400",
    running: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
    pending: "bg-muted text-muted-foreground",
    skipped: "bg-muted text-muted-foreground",
    failed: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
    failed_permanent: "bg-red-500/15 text-red-700 dark:text-red-400",
    locked: "bg-red-500/15 text-red-700 dark:text-red-400",
  };
  return (
    <Badge variant="outline" className={cn("whitespace-nowrap border-transparent font-normal", cls[state])}>
      {t(`etl.states.${state}`, { defaultValue: state })}
    </Badge>
  );
}

/** Relative time with the absolute local time as tooltip. */
export function RelTime({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">--</span>;
  return (
    <time dateTime={value} title={formatDateTimeShort(value)} className="whitespace-nowrap">
      {formatRelative(value)}
    </time>
  );
}

export function AbsTime({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">--</span>;
  return (
    <time dateTime={value} className="whitespace-nowrap">
      {formatDateTimeShort(value)}
    </time>
  );
}

/** Title shown safely as text (no HTML); empty title → id (EC-5). */
export function SourceTitle({ title, id }: { title: string | null | undefined; id: string }) {
  const text = title && title.trim() ? title : id;
  return <span className="break-words [overflow-wrap:anywhere]">{text}</span>;
}

export function Pager({
  total,
  offset,
  limit,
  onChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  const { t } = useTranslation();
  if (total <= limit) return null;
  return (
    <div className="flex items-center justify-between gap-2 pt-2 text-sm">
      <span className="text-muted-foreground">
        {t("etl.pager.range", { from: offset + 1, to: Math.min(total, offset + limit), total })}
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          {t("etl.pager.prev")}
        </Button>
        <Button size="sm" variant="outline" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          {t("etl.pager.next")}
        </Button>
      </div>
    </div>
  );
}

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  allLabel?: string;
  className?: string;
}) {
  return (
    <Select value={value || ALL} onValueChange={(v) => onChange(v === ALL ? "" : v)}>
      <SelectTrigger className={cn("h-8 w-[150px] text-xs", className)} aria-label={label}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {allLabel && <SelectItem value={ALL}>{allLabel}</SelectItem>}
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  text,
  confirm,
  cancel,
  onConfirm,
  destructive,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  text: string;
  confirm: string;
  cancel?: string;
  onConfirm: () => void;
  destructive?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{text}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancel ?? t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className={cn(destructive && "bg-destructive text-destructive-foreground hover:bg-destructive/90")}
          >
            {confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">{text}</p>;
}

/** Horizontal scroll container for wide tables/matrix: the page itself never scrolls sideways (AK-45). */
export function ScrollBox({ children }: { children: React.ReactNode }) {
  return <div className="w-full max-w-full overflow-x-auto rounded-md border">{children}</div>;
}

/**
 * Loads a section's data on mount, when `key` changes and on every refresh tick. Keeps the last
 * data when a reload fails (shown as outdated by the banner) and reports the outcome (AK-41).
 * A 403 sends the user away like the other admin areas (EC-8).
 */
export function useEtlData<T>(
  load: (() => Promise<T>) | null,
  key: string,
  service: "register" | "rebuild"
): { data: T | null; loading: boolean; failed: boolean; notFound: boolean } {
  const { tick, report } = useEtl();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const loadRef = useRef(load);
  loadRef.current = load;
  const lastKey = useRef<string | null>(null);

  useEffect(() => {
    const fn = loadRef.current;
    if (!fn) return;
    let cancelled = false;
    if (lastKey.current !== key) {
      lastKey.current = key;
      setLoading(true);
      setData(null);
      setNotFound(false);
    }
    fn()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setFailed(false);
        setNotFound(false);
        report(service, true);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof EtlError && e.status === 403) {
          window.location.href = "/";
          return;
        }
        if (e instanceof EtlError && (e.status === 404 || e.status === 422)) {
          setNotFound(true);
          setFailed(false);
          report(service, true);
          return;
        }
        setFailed(true);
        report(service, false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  return { data, loading, failed, notFound };
}
