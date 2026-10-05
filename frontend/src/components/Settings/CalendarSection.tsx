"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CalendarDays, CheckCircle2, Plus, RefreshCw, Star, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useCalendarAccounts } from "@/hooks/useCalendarAccounts";
import {
  CalendarApiError,
  disconnectGoogleAccount,
  startCalendarConsent,
  type CalendarAccount,
  type GoogleCalendar,
} from "@/services/calendar";
import { DisconnectGoogleDialog } from "./DisconnectGoogleDialog";

type Notice = { kind: "success" | "error"; text: string } | null;

const KNOWN_REASONS = ["access_denied", "invalid_state", "no_refresh_token", "google_unreachable"];

/**
 * PROJ-87 — Settings tab "Kalender": connect Google accounts, pick which of
 * their calendars Alice may use and which one is the default for new events.
 * Calendars are loaded live from Google; only the selection is stored.
 */
export function CalendarSection() {
  const { t } = useTranslation();
  const { accounts, requiredScopes, isLoading, error, reload, setActive, setDefault } = useCalendarAccounts();
  const [notice, setNotice] = useState<Notice>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<CalendarAccount | null>(null);

  // Result of the Google consent round-trip (?google=connected|error&...).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("google");
    if (!result) return;
    if (result === "connected") {
      setNotice({ kind: "success", text: t("settings.calendar.notice.connected", { account: params.get("account") ?? "" }) });
    } else {
      const reason = params.get("reason") ?? "";
      setNotice({
        kind: "error",
        text: KNOWN_REASONS.includes(reason)
          ? t(`settings.calendar.notice.reasons.${reason}`)
          : t("settings.calendar.notice.failed"),
      });
    }
    // Drop the parameters so a reload doesn't repeat the message.
    window.history.replaceState(null, "", window.location.pathname);
  }, [t]);

  async function connect() {
    setNotice(null);
    setConnecting(true);
    try {
      window.location.href = await startCalendarConsent(requiredScopes);
    } catch {
      setNotice({ kind: "error", text: t("settings.calendar.notice.startFailed") });
      setConnecting(false);
    }
  }

  async function run(key: string, action: () => Promise<void>) {
    setNotice(null);
    setBusyKey(key);
    try {
      await action();
    } catch (err) {
      const status = err instanceof CalendarApiError ? err.status : 0;
      setNotice({
        kind: "error",
        text: status === 409 ? t("settings.calendar.errors.reauth")
          : status === 502 ? t("settings.calendar.errors.unavailable")
          : t("settings.calendar.errors.saveFailed"),
      });
      if (status === 404 || status === 409) void reload(true);
    } finally {
      setBusyKey(null);
    }
  }

  async function disconnect(connectionId: string) {
    await disconnectGoogleAccount(connectionId);
    setNotice({ kind: "success", text: t("settings.calendar.notice.disconnected") });
    await reload(true);
  }

  if (isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-40 bg-muted" />
          <Skeleton className="h-9 w-40 bg-muted" />
        </div>
        {[1, 2].map((i) => <Skeleton key={i} className="h-32 w-full bg-muted" />)}
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" className="border-red-300 bg-red-50 dark:bg-red-900/30 dark:border-red-800">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between gap-2">
          <span>
            {error instanceof CalendarApiError && error.status === 403
              ? t("settings.calendar.errors.forbidden")
              : t("settings.calendar.errors.loadFailed")}
          </span>
          <Button variant="ghost" size="sm" onClick={() => reload()} className="text-red-300 hover:text-red-100">
            <RefreshCw className="mr-2 h-4 w-4" />
            {t("common.retry")}
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {notice && (
        <Alert
          variant={notice.kind === "error" ? "destructive" : "default"}
          className={notice.kind === "error"
            ? "border-red-300 bg-red-50 text-red-800 dark:bg-red-900/30 dark:border-red-800 dark:text-red-300"
            : "border-green-300 bg-green-50 text-green-800 dark:bg-green-900/30 dark:border-green-800 dark:text-green-200"}
        >
          {notice.kind === "error" ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{notice.text}</span>
            <Button variant="ghost" size="sm" onClick={() => setNotice(null)} className="h-auto py-0 px-2">
              {t("common.close")}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-foreground">{t("settings.calendar.title")}</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={() => reload()} title={t("settings.calendar.refresh")}
            aria-label={t("settings.calendar.refresh")} className="text-muted-foreground hover:text-foreground">
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button onClick={connect} disabled={connecting} size="sm" className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white">
            <Plus className="h-4 w-4" />
            {t("settings.calendar.connect")}
          </Button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-10 text-center">
          <CalendarDays className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground font-medium">{t("settings.calendar.emptyTitle")}</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">{t("settings.calendar.emptyDesc")}</p>
          <Button onClick={connect} disabled={connecting} size="sm" className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white">
            <Plus className="h-4 w-4" />
            {t("settings.calendar.connect")}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {accounts.map((acc) => (
            <AccountCard
              key={acc.connection_id}
              account={acc}
              busyKey={busyKey}
              connecting={connecting}
              onConnect={connect}
              onDisconnect={() => setDisconnectTarget(acc)}
              onToggle={(cal, v) => run(`${acc.connection_id}:${cal.id}`, () => setActive(acc.connection_id, cal.id, v))}
              onDefault={(cal) => run(`${acc.connection_id}:${cal.id}`, () => setDefault(acc.connection_id, cal.id))}
            />
          ))}
          <p className="text-xs text-muted-foreground">{t("settings.calendar.privacyHint")}</p>
        </div>
      )}

      {disconnectTarget && (
        <DisconnectGoogleDialog
          account={disconnectTarget}
          open={!!disconnectTarget}
          onOpenChange={(o) => { if (!o) setDisconnectTarget(null); }}
          onConfirm={disconnect}
        />
      )}
    </div>
  );
}

interface AccountCardProps {
  account: CalendarAccount;
  busyKey: string | null;
  connecting: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  onToggle: (cal: GoogleCalendar, active: boolean) => void;
  onDefault: (cal: GoogleCalendar) => void;
}

function AccountCard({ account, busyKey, connecting, onConnect, onDisconnect, onToggle, onDefault }: AccountCardProps) {
  const { t } = useTranslation();
  const isError = account.status === "error" || account.calendars_error === "reauth_required";

  return (
    <section className="rounded-lg border border-border bg-card" aria-label={account.google_account}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium text-foreground">{account.google_account}</span>
          {isError ? (
            <Badge variant="outline" className="text-xs bg-red-100 text-red-800 border-red-300 dark:bg-red-900/50 dark:text-red-300 dark:border-red-700">
              {t("settings.calendar.status.error")}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs bg-green-100 text-green-800 border-green-300 dark:bg-green-900/50 dark:text-green-300 dark:border-green-700">
              {t("settings.calendar.status.active")}
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isError && (
            <Button size="sm" variant="outline" onClick={onConnect} disabled={connecting}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              {t("settings.calendar.reconnect")}
            </Button>
          )}
          {!account.has_calendar_scope && !isError && (
            <Button size="sm" variant="outline" onClick={onConnect} disabled={connecting}>
              {t("settings.calendar.grantAccess")}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onDisconnect} className="text-red-400 hover:text-red-300">
            <Unplug className="mr-1.5 h-4 w-4" />
            {t("settings.calendar.disconnect")}
          </Button>
        </div>
      </header>

      <div className="p-4">
        {!account.has_calendar_scope ? (
          <p className="text-sm text-muted-foreground">{t("settings.calendar.noScope")}</p>
        ) : account.calendars_error === "reauth_required" || account.status === "error" ? (
          <p className="text-sm text-red-400">{t("settings.calendar.errors.reauth")}</p>
        ) : account.calendars_error === "unavailable" ? (
          <p className="text-sm text-red-400">{t("settings.calendar.errors.unavailable")}</p>
        ) : !account.calendars || account.calendars.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("settings.calendar.noCalendars")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {account.calendars.map((cal) => {
              const key = `${account.connection_id}:${cal.id}`;
              const busy = busyKey === key;
              const switchId = `cal-active-${key}`;
              return (
                <li key={cal.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <div className="flex min-w-0 items-center gap-2">
                    {/* Calendar colour comes from Google at runtime — only expressible as inline style. */}
                    <span
                      className="h-3 w-3 shrink-0 rounded-full border border-border bg-muted"
                      style={cal.color ? { backgroundColor: cal.color } : undefined}
                      aria-hidden="true"
                    />
                    <label htmlFor={switchId} className="truncate text-sm text-foreground">{cal.name}</label>
                    {cal.read_only && (
                      <Badge variant="outline" className="text-xs text-muted-foreground border-border">
                        {t("settings.calendar.readOnly")}
                      </Badge>
                    )}
                    {cal.is_default && (
                      <Badge variant="outline" className="text-xs bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/50 dark:text-blue-300 dark:border-blue-700">
                        {t("settings.calendar.default")}
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    {cal.is_active && !cal.read_only && !cal.is_default && (
                      <Button
                        size="sm" variant="ghost" disabled={busy}
                        onClick={() => onDefault(cal)}
                        className="h-8 gap-1 text-muted-foreground hover:text-foreground"
                        title={t("settings.calendar.makeDefault")}
                      >
                        <Star className="h-4 w-4" />
                        <span className="hidden sm:inline">{t("settings.calendar.makeDefault")}</span>
                      </Button>
                    )}
                    <div className="flex items-center gap-2">
                      <span className="hidden text-xs text-muted-foreground sm:inline">{t("settings.calendar.activeForAlice")}</span>
                      <Switch
                        id={switchId}
                        checked={cal.is_active}
                        disabled={busy}
                        onCheckedChange={(v) => onToggle(cal, v)}
                        aria-label={t("settings.calendar.activeForAliceAria", { name: cal.name })}
                      />
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
