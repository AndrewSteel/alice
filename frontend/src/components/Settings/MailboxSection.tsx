"use client";

import { useState } from "react";
import { Plus, Pencil, Trash2, Users, AlertCircle, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/useAuth";
import { useMailboxes } from "@/hooks/useMailboxes";
import { AddMailboxDialog } from "./AddMailboxDialog";
import { EditMailboxDialog } from "./EditMailboxDialog";
import { DeleteMailboxDialog } from "./DeleteMailboxDialog";
import { AccessDialog } from "./AccessDialog";
import type { Mailbox, CreateMailboxInput, UpdateMailboxInput, CreateMailboxResult } from "@/services/mailApi";

function StatusBadge({ status }: { status: Mailbox["status"] }) {
  const map: Record<Mailbox["status"], { label: string; className: string }> = {
    active:         { label: "Aktiv",              className: "bg-green-900/50 text-green-300 border-green-700" },
    syncing:        { label: "Synchronisiert…",    className: "bg-blue-900/50 text-blue-300 border-blue-700" },
    error:          { label: "Fehler",             className: "bg-red-900/50 text-red-300 border-red-700" },
    unclassified:   { label: "Unklassifiziert",    className: "bg-yellow-900/50 text-yellow-300 border-yellow-700" },
  };
  const { label, className } = map[status] ?? map.active;
  return <Badge variant="outline" className={`text-xs ${className}`}>{label}</Badge>;
}

export function MailboxSection() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { mailboxes, isLoading, error, addMailbox, editMailbox, removeMailbox, reload } = useMailboxes();

  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Mailbox | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Mailbox | null>(null);
  const [accessTarget, setAccessTarget] = useState<Mailbox | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleAdd(data: CreateMailboxInput): Promise<CreateMailboxResult> {
    setActionError(null);
    try {
      return await addMailbox(data);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Erstellen.");
      throw err;
    }
  }

  async function handleEdit(data: UpdateMailboxInput) {
    setActionError(null);
    try {
      await editMailbox(data);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Aktualisieren.");
      throw err;
    }
  }

  async function handleDelete(id: string) {
    setActionError(null);
    try {
      await removeMailbox(id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Löschen.");
      throw err;
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-40 bg-muted" />
          <Skeleton className="h-9 w-44 bg-muted" />
        </div>
        {[1, 2].map((i) => <Skeleton key={i} className="h-14 w-full bg-muted" />)}
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" className="bg-red-900/30 border-red-800">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {actionError && (
        <Alert variant="destructive" className="bg-red-900/30 border-red-800">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between">
            <span>{actionError}</span>
            <Button variant="ghost" size="sm" onClick={() => setActionError(null)}
              className="text-red-300 hover:text-red-100 h-auto py-0 px-2">Schließen</Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">
          {isAdmin ? "Alle Postfächer" : "Meine Postfächer"}
        </h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={() => reload()} className="text-muted-foreground hover:text-foreground"
            title="Aktualisieren">
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button onClick={() => { setActionError(null); setAddOpen(true); }}
            size="sm" className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white">
            <Plus className="h-4 w-4" />
            Postfach hinzufügen
          </Button>
        </div>
      </div>

      {mailboxes.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-10 text-center">
          <Mail className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground font-medium">Noch kein Postfach konfiguriert.</p>
          <p className="text-sm text-muted-foreground mt-1">
            Füge ein IMAP-Postfach hinzu, damit Alice deine Mails indexiert.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <Table>
            <TableHeader className="bg-card">
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-muted-foreground">Anzeigename</TableHead>
                <TableHead className="text-muted-foreground">Host</TableHead>
                {isAdmin && <TableHead className="text-muted-foreground">Besitzer</TableHead>}
                <TableHead className="text-muted-foreground">Status</TableHead>
                <TableHead className="text-muted-foreground text-right">Mails</TableHead>
                <TableHead className="text-muted-foreground">Zugriff</TableHead>
                <TableHead className="text-muted-foreground text-right">Aktionen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mailboxes.map((mb) => {
                const isOwner = mb.owner_id === user?.id;
                const canManage = isOwner || isAdmin;
                return (
                  <TableRow key={mb.id} className="border-border hover:bg-accent/50">
                    <TableCell className="text-foreground font-medium">{mb.display_name}</TableCell>
                    <TableCell className="text-muted-foreground text-sm font-mono">
                      {canManage ? `${mb.imap_host}:${mb.imap_port}` : "••••••••"}
                    </TableCell>
                    {isAdmin && (
                      <TableCell className="text-muted-foreground text-sm">{mb.owner_name ?? "—"}</TableCell>
                    )}
                    <TableCell>
                      <div className="space-y-1">
                        <StatusBadge status={mb.status} />
                        {mb.status === "error" && mb.last_error && (
                          <p className="text-xs text-red-400 max-w-[180px] truncate" title={mb.last_error}>
                            {mb.last_error}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm text-right">{mb.mails_indexed}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {(mb.access_users ?? []).length === 0
                        ? "nur Eigentümer"
                        : (mb.access_users ?? []).map((u) => u.display_name).join(", ")}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {isOwner && (
                          <Button variant="ghost" size="icon" onClick={() => setAccessTarget(mb)}
                            className="h-8 w-8 text-muted-foreground hover:text-foreground" title="Zugriffsrechte">
                            <Users className="h-4 w-4" />
                          </Button>
                        )}
                        {isOwner && (
                          <Button variant="ghost" size="icon" onClick={() => setEditTarget(mb)}
                            className="h-8 w-8 text-muted-foreground hover:text-foreground" title="Bearbeiten">
                            <Pencil className="h-4 w-4" />
                          </Button>
                        )}
                        {canManage && (
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(mb)}
                            className="h-8 w-8 text-muted-foreground hover:text-red-400" title="Löschen">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <AddMailboxDialog open={addOpen} onOpenChange={setAddOpen} onSubmit={handleAdd} />

      {editTarget && (
        <EditMailboxDialog
          mailbox={editTarget}
          open={!!editTarget}
          onOpenChange={(o) => { if (!o) setEditTarget(null); }}
          onSubmit={handleEdit}
        />
      )}

      {deleteTarget && (
        <DeleteMailboxDialog
          mailbox={deleteTarget}
          open={!!deleteTarget}
          onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
          onConfirm={handleDelete}
        />
      )}

      {accessTarget && (
        <AccessDialog
          mailbox={accessTarget}
          open={!!accessTarget}
          onOpenChange={(o) => { if (!o) setAccessTarget(null); }}
          onSaved={reload}
        />
      )}
    </div>
  );
}
