"use client";

import { useState } from "react";
import { Plus, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useDmsFolders } from "@/hooks/useDmsFolders";
import { FoldersTable } from "./FoldersTable";
import { AddFolderDialog } from "./AddFolderDialog";
import { EditFolderDialog } from "./EditFolderDialog";
import { DeleteFolderDialog } from "./DeleteFolderDialog";
import type { DmsFolder, CreateFolderInput, UpdateFolderInput } from "@/services/dms";

export function DmsSection() {
  const {
    folders,
    isLoading,
    isReordering,
    error,
    addFolder,
    editFolder,
    removeFolder,
    toggleFolder,
    reorderFolders,
    clearError,
  } = useDmsFolders();

  const { toast } = useToast();
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<DmsFolder | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DmsFolder | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleAdd(data: CreateFolderInput) {
    setActionError(null);
    try {
      await addFolder(data);
      setAddOpen(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Erstellen.");
      throw err; // Let dialog know it failed
    }
  }

  async function handleEdit(id: number, data: UpdateFolderInput) {
    setActionError(null);
    try {
      await editFolder(id, data);
      setEditTarget(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Aktualisieren.");
      throw err;
    }
  }

  async function handleDelete(id: number) {
    setActionError(null);
    try {
      await removeFolder(id);
      setDeleteTarget(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Loeschen.");
    }
  }

  async function handleToggle(folder: DmsFolder) {
    setActionError(null);
    try {
      await toggleFolder(folder.id, !folder.enabled);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Fehler beim Umschalten.");
    }
  }

  async function handleReorder(reorderedFolders: DmsFolder[]) {
    try {
      await reorderFolders(reorderedFolders);
    } catch (err) {
      toast({
        title: "Fehler",
        description: err instanceof Error ? err.message : "Reihenfolge konnte nicht gespeichert werden.",
        variant: "destructive",
      });
    }
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-32 bg-gray-700" />
          <Skeleton className="h-9 w-40 bg-gray-700" />
        </div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full bg-gray-700" />
          ))}
        </div>
      </div>
    );
  }

  // Error state (fetch error)
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
      {/* Action error banner */}
      {actionError && (
        <Alert variant="destructive" className="bg-red-900/30 border-red-800">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between">
            <span>{actionError}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setActionError(null)}
              className="text-red-300 hover:text-red-100 h-auto py-0 px-2"
            >
              Schliessen
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Section header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">DMS Ordner</h2>
        <Button
          onClick={() => { setActionError(null); setAddOpen(true); }}
          size="sm"
          className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white"
        >
          <Plus className="h-4 w-4" />
          Ordner hinzufuegen
        </Button>
      </div>

      {/* Table or empty state */}
      {folders.length === 0 ? (
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-8 text-center">
          <p className="text-gray-400">Noch keine Ordner konfiguriert.</p>
          <p className="text-sm text-gray-500 mt-1">
            Fuege einen NAS-Ordner hinzu, um das DMS zu starten.
          </p>
        </div>
      ) : (
        <FoldersTable
          folders={folders}
          isReordering={isReordering}
          onEdit={setEditTarget}
          onDelete={setDeleteTarget}
          onToggle={handleToggle}
          onReorder={handleReorder}
        />
      )}

      {/* Dialogs */}
      <AddFolderDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSubmit={handleAdd}
      />

      {editTarget && (
        <EditFolderDialog
          folder={editTarget}
          open={!!editTarget}
          onOpenChange={(open) => { if (!open) setEditTarget(null); }}
          onSubmit={handleEdit}
        />
      )}

      {deleteTarget && (
        <DeleteFolderDialog
          folder={deleteTarget}
          open={!!deleteTarget}
          onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
          onConfirm={handleDelete}
        />
      )}
    </div>
  );
}
