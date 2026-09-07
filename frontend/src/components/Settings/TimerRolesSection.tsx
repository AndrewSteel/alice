"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import {
  getTimerConfig,
  updateTimerConfig,
  type TimerConfig,
  type TimerRole,
  type TimerRoleConfig,
} from "@/services/timers";

const ROLES: TimerRole[] = ["admin", "user", "guest", "child"];

/**
 * PROJ-85 — per-role timer permission + caps, plus the default role for a
 * Voice-PE timer whose speaker was not identified. Rendered inside the
 * "Nutzer-Verwaltung" settings tab (admin only — the tab guard already
 * enforces that).
 */
export function TimerRolesSection() {
  const { t } = useTranslation();
  const { toast } = useToast();

  const [config, setConfig] = useState<TimerConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      setConfig(await getTimerConfig());
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.unknownError"));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function patchRole(role: TimerRole, patch: Partial<TimerRoleConfig>) {
    setConfig((prev) =>
      prev
        ? {
            ...prev,
            roles: prev.roles.map((r) =>
              r.role === role ? { ...r, ...patch } : r
            ),
          }
        : prev
    );
  }

  async function save() {
    if (!config) return;
    setIsSaving(true);
    try {
      const saved = await updateTimerConfig({
        default_role: config.default_role,
        roles: config.roles,
      });
      setConfig(saved);
      toast({
        title: t("settings.timers.saved"),
        description: t("settings.timers.savedDesc"),
      });
    } catch (err) {
      toast({
        title: t("common.error"),
        description: err instanceof Error ? err.message : t("common.unknownError"),
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-40 bg-muted" />
        <Skeleton className="h-24 w-full bg-muted" />
      </div>
    );
  }

  if (error || !config) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-900/20 p-4">
        <p className="text-sm text-red-400">{error ?? t("common.unknownError")}</p>
        <Button
          variant="ghost"
          size="sm"
          onClick={load}
          className="mt-2 text-red-400 hover:text-red-300"
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  return (
    <section className="space-y-4" aria-labelledby="timer-roles-heading">
      <div className="flex items-center justify-between">
        <h3
          id="timer-roles-heading"
          className="text-base font-semibold text-foreground"
        >
          {t("settings.timers.heading")}
        </h3>
      </div>

      {/* Default role */}
      <div className="rounded-lg border border-border p-4">
        <Label className="text-sm text-foreground">
          {t("settings.timers.defaultRole")}
        </Label>
        <p className="mb-2 text-xs text-muted-foreground">
          {t("settings.timers.defaultRoleHint")}
        </p>
        <Select
          value={config.default_role}
          onValueChange={(v) =>
            setConfig((prev) =>
              prev ? { ...prev, default_role: v as TimerRole } : prev
            )
          }
        >
          <SelectTrigger className="w-48 bg-card border-border">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            {ROLES.map((r) => (
              <SelectItem key={r} value={r}>
                {t(`settings.timers.roleNames.${r}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Per-role limits */}
      <div className="space-y-3">
        {ROLES.map((role) => {
          const rc = config.roles.find((r) => r.role === role);
          if (!rc) return null;
          return (
            <div
              key={role}
              className="rounded-lg border border-border p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-foreground">
                  {t(`settings.timers.roleNames.${role}`)}
                </span>
                <div className="flex items-center gap-2">
                  <Label
                    htmlFor={`timer-allowed-${role}`}
                    className="text-sm text-muted-foreground"
                  >
                    {t("settings.timers.allowed")}
                  </Label>
                  <Switch
                    id={`timer-allowed-${role}`}
                    checked={rc.can_use_timers}
                    onCheckedChange={(v) =>
                      patchRole(role, { can_use_timers: v })
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <Label
                    htmlFor={`timer-max-active-${role}`}
                    className="text-sm text-foreground"
                  >
                    {t("settings.timers.maxActive")}
                  </Label>
                  <Input
                    id={`timer-max-active-${role}`}
                    type="number"
                    min={0}
                    max={1000}
                    disabled={!rc.can_use_timers}
                    value={rc.timer_max_active}
                    onChange={(e) =>
                      patchRole(role, {
                        timer_max_active: Math.max(0, Number(e.target.value) || 0),
                      })
                    }
                    className="bg-card border-border"
                  />
                </div>
                <div>
                  <Label
                    htmlFor={`timer-max-duration-${role}`}
                    className="text-sm text-foreground"
                  >
                    {t("settings.timers.maxDurationHours")}
                  </Label>
                  <Input
                    id={`timer-max-duration-${role}`}
                    type="number"
                    min={0}
                    max={168}
                    disabled={!rc.can_use_timers}
                    value={Math.round(rc.timer_max_duration_seconds / 3600)}
                    onChange={(e) =>
                      patchRole(role, {
                        timer_max_duration_seconds:
                          Math.max(0, Number(e.target.value) || 0) * 3600,
                      })
                    }
                    className="bg-card border-border"
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex justify-end">
        <Button onClick={save} disabled={isSaving}>
          {isSaving ? t("common.saving") : t("common.save")}
        </Button>
      </div>
    </section>
  );
}
