"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { CalendarAccount } from "@/services/calendar";

interface Props {
  account: CalendarAccount;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (connectionId: string) => Promise<void>;
}

/** PROJ-87 — confirm removing a whole Google connection (all scopes). */
export function DisconnectGoogleDialog({ account, open, onOpenChange, onConfirm }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm(e: React.MouseEvent) {
    e.preventDefault(); // keep the dialog open until the request finished
    setError(null);
    setBusy(true);
    try {
      await onConfirm(account.connection_id);
      onOpenChange(false);
    } catch {
      setError(t("settings.calendar.disconnectError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="bg-card border-border text-foreground">
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.calendar.disconnectDialog.title")}</AlertDialogTitle>
          <AlertDialogDescription className="text-muted-foreground">
            {t("settings.calendar.disconnectDialog.desc", { account: account.google_account })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {account.has_other_scopes && (
          <p className="rounded-md border border-yellow-700 bg-yellow-900/30 p-3 text-sm text-yellow-200" role="alert">
            {t("settings.calendar.disconnectDialog.otherScopesWarning")}
          </p>
        )}
        {error && <p className="text-sm text-red-400 px-1">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel className="bg-muted border-border text-foreground hover:bg-accent" disabled={busy}>
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm} disabled={busy} className="bg-red-600 hover:bg-red-700 text-white">
            {busy ? t("settings.calendar.disconnecting") : t("settings.calendar.disconnectDialog.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
