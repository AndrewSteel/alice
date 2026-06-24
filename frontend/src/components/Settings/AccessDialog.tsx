"use client";

import { useState, useEffect } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle } from "lucide-react";
import { getMailboxAccess, updateMailboxAccess } from "@/services/mailApi";
import type { Mailbox, AccessListUser } from "@/services/mailApi";

interface Props {
  mailbox: Mailbox;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

export function AccessDialog({ mailbox, open, onOpenChange, onSaved }: Props) {
  const [users, setUsers] = useState<AccessListUser[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    getMailboxAccess(mailbox.id)
      .then((data) => {
        setUsers(data);
        setSelected(new Set(data.filter((u) => u.has_access).map((u) => u.user_id)));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Fehler beim Laden."))
      .finally(() => setLoading(false));
  }, [open, mailbox.id]);

  function toggle(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function handleSave() {
    setError(null);
    setSaving(true);
    try {
      await updateMailboxAccess(mailbox.id, Array.from(selected));
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Speichern.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Zugriffsrechte — {mailbox.display_name}</DialogTitle>
          <DialogDescription className="text-gray-400">
            Ausgewählte Nutzer können Mails dieses Postfachs abfragen und erhalten Benachrichtigungen.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="space-y-2 py-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-9 w-full bg-gray-700" />)}
          </div>
        ) : error ? (
          <Alert variant="destructive" className="bg-red-900/30 border-red-800">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-2 py-1 max-h-64 overflow-y-auto">
            {users.length === 0 ? (
              <p className="text-sm text-gray-500 py-4 text-center">Keine Nutzer gefunden.</p>
            ) : (
              users.map((u) => (
                <div key={u.user_id} className="flex items-center gap-3 rounded-md p-2 hover:bg-gray-700/50 cursor-pointer"
                  onClick={() => toggle(u.user_id)}>
                  <Checkbox
                    id={`access-${u.user_id}`}
                    checked={selected.has(u.user_id)}
                    onCheckedChange={() => toggle(u.user_id)}
                    className="border-gray-500 data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
                  />
                  <Label htmlFor={`access-${u.user_id}`} className="cursor-pointer text-gray-200 flex-1">
                    {u.display_name}
                    <span className="text-gray-500 text-xs ml-1">@{u.username}</span>
                  </Label>
                </div>
              ))
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}
            className="text-gray-400 hover:text-gray-100">Abbrechen</Button>
          <Button onClick={handleSave} disabled={saving || loading}
            className="bg-blue-600 hover:bg-blue-700 text-white">
            {saving ? "Wird gespeichert..." : "Speichern"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
