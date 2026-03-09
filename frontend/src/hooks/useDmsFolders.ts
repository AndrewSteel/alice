"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DmsFolder,
  CreateFolderInput,
  UpdateFolderInput,
  getFolders,
  createFolder,
  updateFolder,
  deleteFolder,
} from "@/services/dms";

interface UseDmsFoldersReturn {
  folders: DmsFolder[];
  isLoading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  addFolder: (data: CreateFolderInput) => Promise<void>;
  editFolder: (id: number, data: UpdateFolderInput) => Promise<void>;
  removeFolder: (id: number) => Promise<void>;
  toggleFolder: (id: number, enabled: boolean) => Promise<void>;
  clearError: () => void;
}

export function useDmsFolders(): UseDmsFoldersReturn {
  const [folders, setFolders] = useState<DmsFolder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      setFolders((prev) =>
        [...prev, created].sort((a, b) => a.path.localeCompare(b.path))
      );
    },
    []
  );

  const editFolder = useCallback(
    async (id: number, data: UpdateFolderInput) => {
      const updated = await updateFolder(id, data);
      setFolders((prev) =>
        prev
          .map((f) => (f.id === id ? updated : f))
          .sort((a, b) => a.path.localeCompare(b.path))
      );
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

  const clearError = useCallback(() => setError(null), []);

  return {
    folders,
    isLoading,
    error,
    reload,
    addFolder,
    editFolder,
    removeFolder,
    toggleFolder,
    clearError,
  };
}
