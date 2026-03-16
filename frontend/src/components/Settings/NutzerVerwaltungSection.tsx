"use client";

import { useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { useAdminUsers } from "@/hooks/useAdminUsers";
import type { AdminUser } from "@/services/adminApi";
import { UserTable } from "./UserTable";
import { CreateUserDialog } from "./CreateUserDialog";
import { ResetOtpDialog } from "./ResetOtpDialog";
import { DeactivateUserDialog } from "./DeactivateUserDialog";
import { DeleteUserDialog } from "./DeleteUserDialog";

export function NutzerVerwaltungSection() {
  const { user: currentUser } = useAuth();
  const { toast } = useToast();
  const {
    users,
    isLoading,
    error,
    reload,
    addUser,
    resetUserOtp,
    toggleUserStatus,
    removeUser,
  } = useAdminUsers();

  // Dialog state
  const [createOpen, setCreateOpen] = useState(false);
  const [resetOtpUser, setResetOtpUser] = useState<AdminUser | null>(null);
  const [deactivateUser, setDeactivateUser] = useState<AdminUser | null>(null);
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);

  // --- Handlers ---

  async function handleCreateUser(data: Parameters<typeof addUser>[0]) {
    await addUser(data);
    toast({
      title: "Nutzer angelegt",
      description: "Einmal-Passwort wurde per E-Mail versendet.",
    });
  }

  async function handleResetOtp(userId: string) {
    try {
      await resetUserOtp(userId);
      toast({
        title: "OTP zurueckgesetzt",
        description: "Neues Einmal-Passwort per E-Mail versendet.",
      });
    } catch (err) {
      toast({
        title: "Fehler",
        description:
          err instanceof Error ? err.message : "OTP konnte nicht gesendet werden.",
        variant: "destructive",
      });
      throw err;
    }
  }

  async function handleToggleStatus(userId: string, isActive: boolean) {
    try {
      await toggleUserStatus(userId, isActive);
      toast({
        title: isActive ? "Nutzer aktiviert" : "Nutzer deaktiviert",
        description: isActive
          ? "Der Nutzer kann sich wieder einloggen."
          : "Der Nutzer kann sich nicht mehr einloggen.",
      });
    } catch (err) {
      toast({
        title: "Fehler",
        description:
          err instanceof Error
            ? err.message
            : "Status konnte nicht geaendert werden.",
        variant: "destructive",
      });
      throw err;
    }
  }

  async function handleDeleteUser(userId: string) {
    try {
      const deletedUser = users.find((u) => u.id === userId);
      await removeUser(userId);
      toast({
        title: "Nutzer geloescht",
        description: `${deletedUser?.username ?? "Nutzer"} wurde dauerhaft geloescht.`,
      });
    } catch (err) {
      toast({
        title: "Fehler",
        description:
          err instanceof Error
            ? err.message
            : "Nutzer konnte nicht geloescht werden.",
        variant: "destructive",
      });
      throw err;
    }
  }

  // --- Loading State ---
  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-48 bg-gray-700" />
          <Skeleton className="h-9 w-32 bg-gray-700" />
        </div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full bg-gray-700" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error State ---
  if (error) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-100">
            Nutzerverwaltung
          </h2>
        </div>
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
      {/* Header with actions */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">
          Nutzerverwaltung
        </h2>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={reload}
            className="h-9 w-9 text-gray-400 hover:text-gray-100"
            aria-label="Liste aktualisieren"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            onClick={() => setCreateOpen(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white gap-2"
          >
            <Plus className="h-4 w-4" />
            Neuer Nutzer
          </Button>
        </div>
      </div>

      {/* Empty State */}
      {users.length === 0 ? (
        <div className="rounded-lg border border-gray-700 p-8 text-center">
          <p className="text-gray-400">Keine Nutzer vorhanden.</p>
          <Button
            variant="link"
            onClick={() => setCreateOpen(true)}
            className="mt-2 text-blue-400"
          >
            Ersten Nutzer anlegen
          </Button>
        </div>
      ) : (
        <UserTable
          users={users}
          currentUserId={currentUser?.id ?? ""}
          onResetOtp={(u) => setResetOtpUser(u)}
          onToggleStatus={(u) => setDeactivateUser(u)}
          onDelete={(u) => setDeleteUser(u)}
        />
      )}

      {/* Dialogs */}
      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onConfirm={handleCreateUser}
      />

      {resetOtpUser && (
        <ResetOtpDialog
          user={resetOtpUser}
          open={!!resetOtpUser}
          onOpenChange={(open) => !open && setResetOtpUser(null)}
          onConfirm={handleResetOtp}
        />
      )}

      {deactivateUser && (
        <DeactivateUserDialog
          user={deactivateUser}
          open={!!deactivateUser}
          onOpenChange={(open) => !open && setDeactivateUser(null)}
          onConfirm={handleToggleStatus}
        />
      )}

      {deleteUser && (
        <DeleteUserDialog
          user={deleteUser}
          open={!!deleteUser}
          onOpenChange={(open) => !open && setDeleteUser(null)}
          onConfirm={handleDeleteUser}
        />
      )}
    </div>
  );
}
