"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import {
  getListsRoles,
  updateListsRoles,
  type ListsRole,
  type ListsRoleFlag,
} from "@/services/lists";

const ROLES: ListsRole[] = ["admin", "user", "guest", "child"];

/**
 * PROJ-106 — per-role lists permission. Rendered inside the
 * "Nutzer-Verwaltung" settings tab next to the calendar roles (admin only).
 */
export function ListsRolesSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [roles, setRoles] = useState<ListsRoleFlag[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = async () => {
    setIsLoading(true);
    setFailed(false);
    try {
      setRoles(await getListsRoles());
    } catch {
      setFailed(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  async function save() {
    if (!roles) return;
    setIsSaving(true);
    try {
      setRoles(await updateListsRoles(roles));
      toast({ title: t("settings.listsRoles.saved") });
    } catch {
      toast({ title: t("common.error"), description: t("settings.listsRoles.saveFailed"), variant: "destructive" });
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-40 bg-muted" />
        <Skeleton className="h-16 w-full bg-muted" />
      </div>
    );
  }

  if (failed || !roles) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-900/20 p-4">
        <p className="text-sm text-red-400">{t("settings.listsRoles.loadFailed")}</p>
        <Button variant="ghost" size="sm" onClick={load} className="mt-2 text-red-400 hover:text-red-300">
          <RefreshCw className="mr-2 h-4 w-4" />
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  return (
    <section className="space-y-4" aria-labelledby="lists-roles-heading">
      <div>
        <h3 id="lists-roles-heading" className="text-base font-semibold text-foreground">
          {t("settings.listsRoles.heading")}
        </h3>
        <p className="text-xs text-muted-foreground">{t("settings.listsRoles.hint")}</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {ROLES.map((role) => {
          const rc = roles.find((r) => r.role === role);
          if (!rc) return null;
          return (
            <div key={role} className="flex items-center justify-between rounded-lg border border-border p-4">
              <Label htmlFor={`lists-allowed-${role}`} className="font-medium text-foreground">
                {t(`settings.timers.roleNames.${role}`)}
              </Label>
              <Switch
                id={`lists-allowed-${role}`}
                checked={rc.can_use_lists}
                onCheckedChange={(v) =>
                  setRoles((prev) => prev?.map((r) => (r.role === role ? { ...r, can_use_lists: v } : r)) ?? prev)
                }
              />
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
