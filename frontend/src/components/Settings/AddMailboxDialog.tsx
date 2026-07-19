"use client";

import { useState } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CheckCircle, AlertCircle } from "lucide-react";
import type { CreateMailboxInput, CreateMailboxResult } from "@/services/mailApi";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: CreateMailboxInput) => Promise<CreateMailboxResult>;
}

const DEFAULTS = {
  display_name: "",
  imap_host: "",
  imap_port: "993",
  imap_username: "",
  password: "",
  ssl_enabled: true,
  sync_interval: "15",
  start_date: "",
};

export function AddMailboxDialog({ open, onOpenChange, onSubmit }: Props) {
  const [form, setForm] = useState(DEFAULTS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connResult, setConnResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [prefill, setPrefill] = useState<typeof DEFAULTS | null>(null);

  function reset() {
    setForm(prefill ?? DEFAULTS);
    setError(null);
    setConnResult(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  function set(field: keyof typeof DEFAULTS, value: string | boolean) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setConnResult(null);

    const port = parseInt(form.imap_port);
    const interval = parseInt(form.sync_interval);

    if (!form.display_name.trim()) { setError("Anzeigename ist erforderlich."); return; }
    if (!form.imap_host.trim()) { setError("IMAP-Host ist erforderlich."); return; }
    if (!form.imap_username.trim()) { setError("Benutzername ist erforderlich."); return; }
    if (!form.password) { setError("Passwort ist erforderlich."); return; }
    if (isNaN(port) || port < 1 || port > 65535) { setError("Port muss zwischen 1 und 65535 liegen."); return; }
    if (isNaN(interval) || interval < 1 || interval > 1440) { setError("Sync-Intervall muss zwischen 1 und 1440 Minuten liegen."); return; }

    setSubmitting(true);
    try {
      const result = await onSubmit({
        display_name: form.display_name.trim(),
        imap_host: form.imap_host.trim(),
        imap_port: port,
        imap_username: form.imap_username.trim(),
        password: form.password,
        ssl_enabled: form.ssl_enabled,
        sync_interval: interval,
        start_date: form.start_date || null,
      });
      setConnResult(result.connection_test);
      if (result.connection_test.ok) {
        setPrefill(null);
        setTimeout(() => { handleOpenChange(false); }, 1200);
      } else {
        setPrefill({ ...form, password: "" });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Erstellen.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-card border-border text-foreground sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Postfach hinzufügen</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            IMAP-Zugangsdaten konfigurieren. Das Passwort wird verschlüsselt gespeichert.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="mb-name" className="text-foreground">Anzeigename <span className="text-red-400">*</span></Label>
            <Input id="mb-name" value={form.display_name} onChange={(e) => set("display_name", e.target.value)}
              placeholder="Mein Gmail-Postfach" className="bg-background border-border text-foreground placeholder:text-muted-foreground" autoFocus />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-2">
              <Label htmlFor="mb-host" className="text-foreground">IMAP-Host <span className="text-red-400">*</span></Label>
              <Input id="mb-host" value={form.imap_host} onChange={(e) => set("imap_host", e.target.value)}
                placeholder="imap.gmail.com" className="bg-background border-border text-foreground placeholder:text-muted-foreground font-mono text-sm" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mb-port" className="text-foreground">Port <span className="text-red-400">*</span></Label>
              <Input id="mb-port" value={form.imap_port} onChange={(e) => set("imap_port", e.target.value)}
                type="number" min={1} max={65535} className="bg-background border-border text-foreground" />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="mb-user" className="text-foreground">Benutzername <span className="text-red-400">*</span></Label>
            <Input id="mb-user" value={form.imap_username} onChange={(e) => set("imap_username", e.target.value)}
              placeholder="nutzer@example.com" autoComplete="username"
              className="bg-background border-border text-foreground placeholder:text-muted-foreground" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="mb-pass" className="text-foreground">Passwort <span className="text-red-400">*</span></Label>
            <Input id="mb-pass" type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
              autoComplete="new-password"
              className="bg-background border-border text-foreground" />
          </div>

          <div className="flex items-center gap-3">
            <Switch id="mb-ssl" checked={form.ssl_enabled} onCheckedChange={(v) => set("ssl_enabled", v)} />
            <Label htmlFor="mb-ssl" className="text-foreground cursor-pointer">SSL/TLS aktivieren</Label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="mb-interval" className="text-foreground">Sync-Intervall (Minuten) <span className="text-red-400">*</span></Label>
              <Input id="mb-interval" value={form.sync_interval} onChange={(e) => set("sync_interval", e.target.value)}
                type="number" min={1} max={1440} className="bg-background border-border text-foreground" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mb-date" className="text-foreground">Startdatum (optional)</Label>
              <Input id="mb-date" type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)}
                className="bg-background border-border text-foreground" />
            </div>
          </div>

          {error && (
            <Alert variant="destructive" className="bg-red-900/30 border-red-800 py-2">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {connResult && (
            <Alert className={connResult.ok
              ? "bg-green-900/30 border-green-700 py-2"
              : "bg-red-900/30 border-red-800 py-2"}>
              {connResult.ok
                ? <CheckCircle className="h-4 w-4 text-green-400" />
                : <AlertCircle className="h-4 w-4" />}
              <AlertDescription className={connResult.ok ? "text-green-300" : ""}>
                {connResult.ok ? "Verbindung erfolgreich — Postfach wurde gespeichert." : connResult.message}
              </AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => handleOpenChange(false)} disabled={submitting}
              className="text-muted-foreground hover:text-foreground">
              Abbrechen
            </Button>
            <Button type="submit" disabled={submitting} className="bg-blue-600 hover:bg-blue-700 text-white">
              {submitting ? "Wird gespeichert..." : "Postfach hinzufügen"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
