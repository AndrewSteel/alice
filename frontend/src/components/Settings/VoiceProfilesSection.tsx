"use client";

import { useState } from "react";
import { RefreshCw, Trash2, Mic } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { useVoiceProfiles } from "@/hooks/useVoiceProfiles";
import type { VoiceProfile } from "@/services/voiceApi";

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  try {
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(dateStr));
  } catch {
    return dateStr;
  }
}

export function VoiceProfilesSection() {
  const { toast } = useToast();
  const { profiles, isLoading, error, reload, removeProfile } = useVoiceProfiles();
  const [deleteTarget, setDeleteTarget] = useState<VoiceProfile | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleDelete() {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await removeProfile(deleteTarget.user_id);
      toast({
        title: "Stimmprofil geloescht",
        description: `Das Stimmprofil von ${deleteTarget.username} wurde entfernt.`,
      });
      setDeleteTarget(null);
    } catch (err) {
      toast({
        title: "Fehler",
        description:
          err instanceof Error
            ? err.message
            : "Stimmprofil konnte nicht geloescht werden.",
        variant: "destructive",
      });
    } finally {
      setIsDeleting(false);
    }
  }

  // --- Loading State ---
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-7 w-48 bg-muted" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error State ---
  if (error) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Stimmprofile</h2>
        <div className="rounded-lg border border-red-800 bg-red-900/20 p-4">
          <p className="text-sm text-red-400">{error}</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={reload}
            className="mt-2 text-red-400 hover:text-red-300"
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Erneut versuchen
          </Button>
        </div>
      </div>
    );
  }

  // --- Main Content ---
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Stimmprofile</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={reload}
          className="h-9 w-9 text-muted-foreground hover:text-foreground"
          aria-label="Liste aktualisieren"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        Nutzer, deren Stimme registriert ist. Beim Loeschen werden alle
        Stimmproben entfernt; der Nutzer selbst bleibt erhalten.
      </p>

      {profiles.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center">
          <Mic className="mx-auto h-6 w-6 text-muted-foreground" />
          <p className="mt-2 text-muted-foreground">
            Noch keine Stimmprofile registriert.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          {/* Desktop table */}
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">Nutzer</TableHead>
                  <TableHead className="text-muted-foreground">Rolle</TableHead>
                  <TableHead className="text-muted-foreground">Proben</TableHead>
                  <TableHead className="text-muted-foreground hidden lg:table-cell">
                    Registriert
                  </TableHead>
                  <TableHead className="text-muted-foreground text-right w-10">
                    Aktion
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {profiles.map((p) => (
                  <TableRow
                    key={p.user_id}
                    className="border-border hover:bg-accent/50"
                  >
                    <TableCell>
                      <p className="text-sm font-medium text-foreground">
                        {p.display_name || p.username}
                      </p>
                      {p.display_name && (
                        <p className="text-xs text-muted-foreground">{p.username}</p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className="text-xs bg-muted/40 text-foreground border-border"
                      >
                        {p.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-foreground text-sm tabular-nums">
                      {p.sample_count}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm hidden lg:table-cell">
                      {formatDate(p.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget(p)}
                        className="h-8 w-8 text-muted-foreground hover:text-red-400"
                        aria-label={`Stimmprofil von ${p.username} loeschen`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Mobile card list */}
          <div className="md:hidden divide-y divide-border">
            {profiles.map((p) => (
              <div
                key={p.user_id}
                className="p-4 flex items-start justify-between gap-2"
              >
                <div className="min-w-0 space-y-1">
                  <p className="text-sm font-medium text-foreground truncate">
                    {p.display_name || p.username}
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge
                      variant="secondary"
                      className="text-xs bg-muted/40 text-foreground border-border"
                    >
                      {p.role}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {p.sample_count} Proben
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Registriert: {formatDate(p.created_at)}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setDeleteTarget(p)}
                  className="h-8 w-8 shrink-0 text-muted-foreground hover:text-red-400"
                  aria-label={`Stimmprofil von ${p.username} loeschen`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && !isDeleting && setDeleteTarget(null)}
      >
        <AlertDialogContent className="bg-card border-border text-foreground">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-red-400">
              Stimmprofil loeschen
            </AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Das Stimmprofil von{" "}
              <span className="font-medium text-foreground">
                {deleteTarget?.username}
              </span>{" "}
              wird dauerhaft entfernt. Der Nutzer wird an Sprachgeraeten nicht
              mehr automatisch erkannt, bis die Stimme neu registriert wird.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              disabled={isDeleting}
              className="bg-transparent border-border text-foreground hover:bg-accent hover:text-foreground"
            >
              Abbrechen
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleDelete();
              }}
              disabled={isDeleting}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              {isDeleting ? "Wird geloescht..." : "Loeschen"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
