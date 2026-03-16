"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AdminUser,
  CreateUserInput,
  getUsers,
  createUser,
  resetOtp,
  updateUserStatus,
  deleteUser,
} from "@/services/adminApi";

interface UseAdminUsersReturn {
  users: AdminUser[];
  isLoading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  addUser: (data: CreateUserInput) => Promise<void>;
  resetUserOtp: (userId: string) => Promise<void>;
  toggleUserStatus: (userId: string, isActive: boolean) => Promise<void>;
  removeUser: (userId: string) => Promise<void>;
  clearError: () => void;
}

export function useAdminUsers(): UseAdminUsersReturn {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const addUser = useCallback(
    async (data: CreateUserInput) => {
      const created = await createUser(data);
      setUsers((prev) =>
        [...prev, created].sort((a, b) =>
          a.username.localeCompare(b.username)
        )
      );
    },
    []
  );

  const resetUserOtp = useCallback(
    async (userId: string) => {
      await resetOtp(userId);
      // Update local state: mark user as must_change_password
      setUsers((prev) =>
        prev.map((u) =>
          u.id === userId ? { ...u, must_change_password: true } : u
        )
      );
    },
    []
  );

  const toggleUserStatus = useCallback(
    async (userId: string, isActive: boolean) => {
      await updateUserStatus(userId, isActive);
      setUsers((prev) =>
        prev.map((u) =>
          u.id === userId ? { ...u, is_active: isActive } : u
        )
      );
    },
    []
  );

  const removeUser = useCallback(async (userId: string) => {
    await deleteUser(userId);
    setUsers((prev) => prev.filter((u) => u.id !== userId));
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    users,
    isLoading,
    error,
    reload,
    addUser,
    resetUserOtp,
    toggleUserStatus,
    removeUser,
    clearError,
  };
}
