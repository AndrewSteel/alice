"use client";

import { useState } from "react";
import { Plus, AlertCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useDmsFolders } from "@/hooks/useDmsFolders";
import { FoldersTable } from "./FoldersTable";
import { AddFolderDialog } from "./AddFolderDialog";
import { EditFolderDialog } from "./EditFolderDialog";
import { DeleteFolderDialog } from "./DeleteFolderDialog";
import type {
  DmsFolder,
  CreateFolderInput,
  UpdateFolderInput,
} from "@/services/dms";

export function DmsSection() {
  const { t } = useTranslation();
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
      setActionError(
        err instanceof Error ? err.message : t("settings.dms.createError"),
      );
      throw err; // Let dialog know it failed
    }
  }

  async function handleEdit(id: number, data: UpdateFolderInput) {
    setActionError(null);
    try {
      await editFolder(id, data);
      setEditTarget(null);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : t("settings.dms.updateError"),
      );
      throw err;
    }
  }

  async function handleDelete(id: number) {
    setActionError(null);
    try {
      await removeFolder(id);
      setDeleteTarget(null);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : t("settings.dms.deleteError"),
      );
    }
  }

  async function handleToggle(folder: DmsFolder) {
    setActionError(null);
    try {
      await toggleFolder(folder.id, !folder.enabled);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : t("settings.dms.toggleError"),
      );
    }
  }

  async function handleReorder(reorderedFolders: DmsFolder[]) {
    try {
      await reorderFolders(reorderedFolders);
    } catch (err) {
      toast({
        title: t("common.error"),
        description:
          err instanceof Error
            ? err.message
            : t("settings.dms.reorderError"),
        variant: "destructive",
      });
    }
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-32 bg-muted" />
          <Skeleton className="h-9 w-40 bg-muted" />
        </div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full bg-muted" />
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
              {t("common.close")}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Section header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">{t("settings.dms.title")}</h2>
        <Button
          onClick={() => {
            setActionError(null);
            setAddOpen(true);
          }}
          size="sm"
          className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white"
        >
          <Plus className="h-4 w-4" />
          {t("settings.dms.addFolder")}
        </Button>
      </div>

      {/* Table or empty state */}
      {folders.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <p className="text-muted-foreground">{t("settings.dms.emptyTitle")}</p>
          <p className="text-sm text-muted-foreground mt-1">
            {t("settings.dms.emptyDesc")}
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
          onOpenChange={(open) => {
            if (!open) setEditTarget(null);
          }}
          onSubmit={handleEdit}
        />
      )}

      {deleteTarget && (
        <DeleteFolderDialog
          folder={deleteTarget}
          open={!!deleteTarget}
          onOpenChange={(open) => {
            if (!open) setDeleteTarget(null);
          }}
          onConfirm={handleDelete}
        />
      )}
    </div>
  );
}
