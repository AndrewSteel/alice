"use client";

import { useState, useEffect } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Mailbox, UpdateMailboxInput } from "@/services/mailApi";

interface Props {
  mailbox: Mailbox;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: UpdateMailboxInput) => Promise<void>;
}

export function EditMailboxDialog({ mailbox, open, onOpenChange, onSubmit }: Props) {
  const { t } = useTranslation();
  const [displayName, setDisplayName] = useState(mailbox.display_name);
  const [imapHost, setImapHost] = useState(mailbox.imap_host);
  const [imapPort, setImapPort] = useState(String(mailbox.imap_port));
  const [imapUsername, setImapUsername] = useState(mailbox.imap_username);
  const [password, setPassword] = useState("");
  const [sslEnabled, setSslEnabled] = useState(mailbox.ssl_enabled);
  const [syncInterval, setSyncInterval] = useState(String(mailbox.sync_interval));
  const [startDate, setStartDate] = useState(mailbox.start_date ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDisplayName(mailbox.display_name);
      setImapHost(mailbox.imap_host);
      setImapPort(String(mailbox.imap_port));
      setImapUsername(mailbox.imap_username);
      setPassword("");
      setSslEnabled(mailbox.ssl_enabled);
      setSyncInterval(String(mailbox.sync_interval));
      setStartDate(mailbox.start_date ?? "");
      setError(null);
    }
  }, [open, mailbox]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const port = parseInt(imapPort);
    const interval = parseInt(syncInterval);
    if (!displayName.trim()) { setError(t("settings.mail.addDialog.displayNameRequired")); return; }
    if (isNaN(port) || port < 1 || port > 65535) { setError(t("settings.mail.addDialog.portRange")); return; }
    if (isNaN(interval) || interval < 1 || interval > 1440) { setError(t("settings.mail.addDialog.intervalRange")); return; }

    setSubmitting(true);
    try {
      const data: UpdateMailboxInput = {
        id: mailbox.id,
        display_name: displayName.trim(),
        imap_host: imapHost.trim(),
        imap_port: port,
        imap_username: imapUsername.trim(),
        ssl_enabled: sslEnabled,
        sync_interval: interval,
        start_date: startDate || null,
      };
      if (password) data.password = password;
      await onSubmit(data);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.profilForm.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border text-foreground sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("settings.mail.editDialog.title")}</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {t("settings.mail.editDialog.desc")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label className="text-foreground">{t("settings.mail.addDialog.displayName")} <span className="text-red-400">*</span></Label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="bg-background border-border text-foreground" />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-2">
              <Label className="text-foreground">{t("settings.mail.addDialog.imapHost")}</Label>
              <Input value={imapHost} onChange={(e) => setImapHost(e.target.value)}
                className="bg-background border-border text-foreground font-mono text-sm" />
            </div>
            <div className="space-y-2">
              <Label className="text-foreground">{t("settings.mail.addDialog.port")}</Label>
              <Input value={imapPort} onChange={(e) => setImapPort(e.target.value)}
                type="number" min={1} max={65535} className="bg-background border-border text-foreground" />
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-foreground">{t("settings.mail.addDialog.username")}</Label>
            <Input value={imapUsername} onChange={(e) => setImapUsername(e.target.value)}
              autoComplete="username" className="bg-background border-border text-foreground" />
          </div>

          <div className="space-y-2">
            <Label className="text-foreground">{t("settings.mail.editDialog.newPassword")} <span className="text-muted-foreground text-xs">{t("settings.mail.editDialog.passwordUnchanged")}</span></Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password" placeholder="••••••••"
              className="bg-background border-border text-foreground placeholder:text-muted-foreground" />
          </div>

          <div className="flex items-center gap-3">
            <Switch id="edit-ssl" checked={sslEnabled} onCheckedChange={setSslEnabled} />
            <Label htmlFor="edit-ssl" className="text-foreground cursor-pointer">{t("settings.mail.addDialog.ssl")}</Label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label className="text-foreground">{t("settings.mail.editDialog.syncIntervalShort")} <span className="text-red-400">*</span></Label>
              <Input value={syncInterval} onChange={(e) => setSyncInterval(e.target.value)}
                type="number" min={1} max={1440} className="bg-background border-border text-foreground" />
            </div>
            <div className="space-y-2">
              <Label className="text-foreground">{t("settings.mail.addDialog.startDate")}</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                className="bg-background border-border text-foreground" />
            </div>
          </div>

          {error && (
            <Alert variant="destructive" className="bg-red-900/30 border-red-800 py-2">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}
              className="text-muted-foreground hover:text-foreground">{t("common.cancel")}</Button>
            <Button type="submit" disabled={submitting} className="bg-blue-600 hover:bg-blue-700 text-white">
              {submitting ? t("common.saving") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
