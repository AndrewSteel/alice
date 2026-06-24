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
import type { Mailbox, UpdateMailboxInput } from "@/services/mailApi";

interface Props {
  mailbox: Mailbox;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: UpdateMailboxInput) => Promise<void>;
}

export function EditMailboxDialog({ mailbox, open, onOpenChange, onSubmit }: Props) {
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
    if (!displayName.trim()) { setError("Anzeigename ist erforderlich."); return; }
    if (isNaN(port) || port < 1 || port > 65535) { setError("Port muss zwischen 1 und 65535 liegen."); return; }
    if (isNaN(interval) || interval < 1 || interval > 1440) { setError("Sync-Intervall muss zwischen 1 und 1440 Minuten liegen."); return; }

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
      setError(err instanceof Error ? err.message : "Fehler beim Speichern.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Postfach bearbeiten</DialogTitle>
          <DialogDescription className="text-gray-400">
            Zugangsdaten aktualisieren. Passwortfeld leer lassen, um es unverändert zu behalten.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label className="text-gray-300">Anzeigename <span className="text-red-400">*</span></Label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="bg-gray-900 border-gray-600 text-gray-100" />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-2">
              <Label className="text-gray-300">IMAP-Host</Label>
              <Input value={imapHost} onChange={(e) => setImapHost(e.target.value)}
                className="bg-gray-900 border-gray-600 text-gray-100 font-mono text-sm" />
            </div>
            <div className="space-y-2">
              <Label className="text-gray-300">Port</Label>
              <Input value={imapPort} onChange={(e) => setImapPort(e.target.value)}
                type="number" min={1} max={65535} className="bg-gray-900 border-gray-600 text-gray-100" />
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-gray-300">Benutzername</Label>
            <Input value={imapUsername} onChange={(e) => setImapUsername(e.target.value)}
              autoComplete="username" className="bg-gray-900 border-gray-600 text-gray-100" />
          </div>

          <div className="space-y-2">
            <Label className="text-gray-300">Neues Passwort <span className="text-gray-500 text-xs">(leer = unverändert)</span></Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password" placeholder="••••••••"
              className="bg-gray-900 border-gray-600 text-gray-100 placeholder:text-gray-600" />
          </div>

          <div className="flex items-center gap-3">
            <Switch id="edit-ssl" checked={sslEnabled} onCheckedChange={setSslEnabled} />
            <Label htmlFor="edit-ssl" className="text-gray-300 cursor-pointer">SSL/TLS aktivieren</Label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label className="text-gray-300">Sync-Intervall (Min.) <span className="text-red-400">*</span></Label>
              <Input value={syncInterval} onChange={(e) => setSyncInterval(e.target.value)}
                type="number" min={1} max={1440} className="bg-gray-900 border-gray-600 text-gray-100" />
            </div>
            <div className="space-y-2">
              <Label className="text-gray-300">Startdatum (optional)</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                className="bg-gray-900 border-gray-600 text-gray-100" />
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
              className="text-gray-400 hover:text-gray-100">Abbrechen</Button>
            <Button type="submit" disabled={submitting} className="bg-blue-600 hover:bg-blue-700 text-white">
              {submitting ? "Wird gespeichert..." : "Speichern"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
