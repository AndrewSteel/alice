"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DmsFolder,
  CreateFolderInput,
  UpdateFolderInput,
  getFolders,
  createFolder,
  updateFolder,
  deleteFolder,
  reorderFolders as reorderFoldersApi,
  ReorderEntry,
} from "@/services/dms";

interface UseDmsFoldersReturn {
  folders: DmsFolder[];
  isLoading: boolean;
  isReordering: boolean;
  error: string | null;
  reload: () => Promise<void>;
  addFolder: (data: CreateFolderInput) => Promise<void>;
  editFolder: (id: number, data: UpdateFolderInput) => Promise<void>;
  removeFolder: (id: number) => Promise<void>;
  toggleFolder: (id: number, enabled: boolean) => Promise<void>;
  reorderFolders: (reorderedFolders: DmsFolder[]) => Promise<void>;
  clearError: () => void;
}

export function useDmsFolders(): UseDmsFoldersReturn {
  const [folders, setFolders] = useState<DmsFolder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isReordering, setIsReordering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previousFoldersRef = useRef<DmsFolder[]>([]);

  const reload = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getFolders();
      setFolders(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const addFolder = useCallback(
    async (data: CreateFolderInput) => {
      const created = await createFolder(data);
      setFolders((prev) => [...prev, created]);
    },
    []
  );

  const editFolder = useCallback(
    async (id: number, data: UpdateFolderInput) => {
      const updated = await updateFolder(id, data);
      setFolders((prev) => prev.map((f) => (f.id === id ? updated : f)));
    },
    []
  );

  const removeFolder = useCallback(async (id: number) => {
    await deleteFolder(id);
    setFolders((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const toggleFolder = useCallback(
    async (id: number, enabled: boolean) => {
      const updated = await updateFolder(id, { enabled });
      setFolders((prev) => prev.map((f) => (f.id === id ? updated : f)));
    },
    []
  );

  const reorderFolders = useCallback(
    async (reorderedFolders: DmsFolder[]) => {
      // Save previous state for rollback
      previousFoldersRef.current = folders;

      // Optimistic update: immediately show new order
      setFolders(reorderedFolders);
      setIsReordering(true);

      try {
        const order: ReorderEntry[] = reorderedFolders.map((f, index) => ({
          id: f.id,
          sort_order: index + 1,
        }));
        const updatedFolders = await reorderFoldersApi(order);
        setFolders(updatedFolders);
      } catch {
        // Rollback on error
        setFolders(previousFoldersRef.current);
        throw new Error("Reihenfolge konnte nicht gespeichert werden.");
      } finally {
        setIsReordering(false);
      }
    },
    [folders]
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    folders,
    isLoading,
    isReordering,
    error,
    reload,
    addFolder,
    editFolder,
    removeFolder,
    toggleFolder,
    reorderFolders,
    clearError,
  };
}
