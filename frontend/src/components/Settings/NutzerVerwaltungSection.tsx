"use client";

import { useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { useAdminUsers } from "@/hooks/useAdminUsers";
import type { AdminUser } from "@/services/adminApi";
import { UserTable } from "./UserTable";
import { CreateUserDialog } from "./CreateUserDialog";
import { ResetOtpDialog } from "./ResetOtpDialog";
import { SetCredentialsDialog } from "./SetCredentialsDialog";
import { DeactivateUserDialog } from "./DeactivateUserDialog";
import { DeleteUserDialog } from "./DeleteUserDialog";

export function NutzerVerwaltungSection() {
  const { t } = useTranslation();
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
    toggleVoiceEnrollment,
    setUserCredentials,
    removeUser,
  } = useAdminUsers();

  // Dialog state
  const [createOpen, setCreateOpen] = useState(false);
  const [resetOtpUser, setResetOtpUser] = useState<AdminUser | null>(null);
  const [credentialsUser, setCredentialsUser] = useState<AdminUser | null>(null);
  const [deactivateUser, setDeactivateUser] = useState<AdminUser | null>(null);
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);

  // --- Handlers ---

  async function handleCreateUser(data: Parameters<typeof addUser>[0]) {
    await addUser(data);
    toast({
      title: t("settings.users.created"),
      description: t("settings.users.createdDesc"),
    });
  }

  async function handleResetOtp(userId: string) {
    try {
      await resetUserOtp(userId);
      toast({
        title: t("settings.users.otpReset"),
        description: t("settings.users.otpResetDesc"),
      });
    } catch (err) {
      toast({
        title: t("common.error"),
        description:
          err instanceof Error ? err.message : t("settings.users.otpError"),
        variant: "destructive",
      });
      throw err;
    }
  }

  async function handleToggleStatus(userId: string, isActive: boolean) {
    try {
      await toggleUserStatus(userId, isActive);
      toast({
        title: isActive ? t("settings.users.activated") : t("settings.users.deactivated"),
        description: isActive
          ? t("settings.users.activatedDesc")
          : t("settings.users.deactivatedDesc"),
      });
    } catch (err) {
      toast({
        title: t("common.error"),
        description:
          err instanceof Error
            ? err.message
            : t("settings.users.statusError"),
        variant: "destructive",
      });
      throw err;
    }
  }

  async function handleToggleVoice(user: AdminUser, allow: boolean) {
    try {
      await toggleVoiceEnrollment(user.id, allow);
      toast({
        title: allow
          ? t("settings.users.voiceEnabled")
          : t("settings.users.voiceDisabled"),
        description: allow
          ? t("settings.users.voiceEnabledDesc", { name: user.username })
          : t("settings.users.voiceDisabledDesc", { name: user.username }),
      });
    } catch (err) {
      toast({
        title: t("common.error"),
        description:
          err instanceof Error
            ? err.message
            : t("settings.users.permissionError"),
        variant: "destructive",
      });
    }
  }

  async function handleSetCredentials(userId: string, email: string) {
    await setUserCredentials(userId, email);
    toast({
      title: t("settings.users.accessSet"),
      description: t("settings.users.accessSetDesc"),
    });
  }

  async function handleDeleteUser(userId: string) {
    try {
      const deletedUser = users.find((u) => u.id === userId);
      await removeUser(userId);
      toast({
        title: t("settings.users.deleted"),
        description: t("settings.users.deletedDesc", {
          name: deletedUser?.username ?? t("settings.users.deletedFallback"),
        }),
      });
    } catch (err) {
      toast({
        title: t("common.error"),
        description:
          err instanceof Error
            ? err.message
            : t("settings.users.deleteError"),
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
          <Skeleton className="h-7 w-48 bg-muted" />
          <Skeleton className="h-9 w-32 bg-muted" />
        </div>
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
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">
            {t("settings.users.heading")}
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
            {t("common.retry")}
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
        <h2 className="text-lg font-semibold text-foreground">
          {t("settings.users.heading")}
        </h2>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={reload}
            className="h-9 w-9 text-muted-foreground hover:text-foreground"
            aria-label={t("settings.users.refresh")}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            onClick={() => setCreateOpen(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white gap-2"
          >
            <Plus className="h-4 w-4" />
            {t("settings.users.newUser")}
          </Button>
        </div>
      </div>

      {/* Empty State */}
      {users.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center">
          <p className="text-muted-foreground">{t("settings.users.emptyTitle")}</p>
          <Button
            variant="link"
            onClick={() => setCreateOpen(true)}
            className="mt-2 text-blue-400"
          >
            {t("settings.users.createFirst")}
          </Button>
        </div>
      ) : (
        <UserTable
          users={users}
          currentUserId={currentUser?.id ?? ""}
          onResetOtp={(u) => setResetOtpUser(u)}
          onSetCredentials={(u) => setCredentialsUser(u)}
          onToggleStatus={(u) => setDeactivateUser(u)}
          onToggleVoice={handleToggleVoice}
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

      {credentialsUser && (
        <SetCredentialsDialog
          user={credentialsUser}
          open={!!credentialsUser}
          onOpenChange={(open) => !open && setCredentialsUser(null)}
          onConfirm={handleSetCredentials}
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
