"use client";

import { MoreVertical, KeyRound, UserX, UserCheck, Trash2, Mic, LogIn } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatDate } from "@/i18n/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AdminUser } from "@/services/adminApi";

interface UserTableProps {
  users: AdminUser[];
  currentUserId: string;
  onResetOtp: (user: AdminUser) => void;
  onSetCredentials: (user: AdminUser) => void;
  onToggleStatus: (user: AdminUser) => void;
  onToggleVoice: (user: AdminUser, allow: boolean) => void;
  onDelete: (user: AdminUser) => void;
}

function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    admin: "bg-purple-900/40 text-purple-300 border-purple-800",
    user: "bg-blue-900/40 text-blue-300 border-blue-800",
    guest: "bg-muted/40 text-foreground border-border",
    child: "bg-green-900/40 text-green-300 border-green-800",
  };

  return (
    <Badge
      variant="secondary"
      className={`text-xs ${styles[role] || "bg-muted/40 text-foreground border-border"}`}
    >
      {role}
    </Badge>
  );
}

function StatusBadge({ isActive }: { isActive: boolean }) {
  const { t } = useTranslation();
  if (isActive) {
    return (
      <Badge
        variant="secondary"
        className="text-xs bg-emerald-900/40 text-emerald-300 border-emerald-800"
      >
        {t("settings.users.table.active")}
      </Badge>
    );
  }
  return (
    <Badge
      variant="secondary"
      className="text-xs bg-red-900/40 text-red-300 border-red-800"
    >
      {t("settings.users.table.inactive")}
    </Badge>
  );
}

function VoiceCell({
  user,
  onToggleVoice,
}: {
  user: AdminUser;
  onToggleVoice: (user: AdminUser, allow: boolean) => void;
}) {
  const { t } = useTranslation();
  const enrolled = user.speaker_enrollment_complete;

  // Admins may always self-enroll (bootstrap) — the per-user flag is moot.
  if (user.role === "admin") {
    return (
      <div className="flex items-center gap-2">
        <Badge
          variant="secondary"
          className="text-xs bg-muted/40 text-foreground border-border"
        >
          {t("settings.users.table.always")}
        </Badge>
        {enrolled && <Mic className="h-3.5 w-3.5 text-emerald-400" aria-label={t("settings.users.table.voiceRegistered")} />}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Switch
        checked={user.allow_voice_enrollment}
        onCheckedChange={(checked) => onToggleVoice(user, checked)}
        aria-label={
          user.allow_voice_enrollment
            ? t("settings.users.table.voiceToggleDisableAria", { name: user.username })
            : t("settings.users.table.voiceToggleEnableAria", { name: user.username })
        }
      />
      {enrolled && <Mic className="h-3.5 w-3.5 text-emerald-400" aria-label={t("settings.users.table.voiceRegistered")} />}
    </div>
  );
}

function UserActionMenu({
  user,
  isSelf,
  onResetOtp,
  onSetCredentials,
  onToggleStatus,
  onDelete,
}: {
  user: AdminUser;
  isSelf: boolean;
  onResetOtp: (user: AdminUser) => void;
  onSetCredentials: (user: AdminUser) => void;
  onToggleStatus: (user: AdminUser) => void;
  onDelete: (user: AdminUser) => void;
}) {
  const { t } = useTranslation();
  const hasEmail = !!user.email;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-muted-foreground hover:text-foreground"
          aria-label={t("settings.users.table.actionsFor", { name: user.username })}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="bg-card border-border text-foreground"
      >
        {hasEmail ? (
          <DropdownMenuItem
            onClick={() => onResetOtp(user)}
            className="gap-2 focus:bg-accent focus:text-foreground"
          >
            <KeyRound className="h-4 w-4" />
            {t("settings.users.table.resetOtp")}
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem
            onClick={() => onSetCredentials(user)}
            className="gap-2 focus:bg-accent focus:text-foreground"
          >
            <LogIn className="h-4 w-4" />
            {t("settings.users.table.setupAccess")}
          </DropdownMenuItem>
        )}

        <DropdownMenuSeparator className="bg-muted" />

        {isSelf ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-2 py-1.5 text-sm text-muted-foreground flex items-center gap-2 cursor-not-allowed">
                  {user.is_active ? (
                    <UserX className="h-4 w-4" />
                  ) : (
                    <UserCheck className="h-4 w-4" />
                  )}
                  {user.is_active ? t("settings.users.table.deactivate") : t("settings.users.table.activate")}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {t("settings.users.table.cannotDeactivateSelf")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <DropdownMenuItem
            onClick={() => onToggleStatus(user)}
            className="gap-2 focus:bg-accent focus:text-foreground"
          >
            {user.is_active ? (
              <>
                <UserX className="h-4 w-4" />
                {t("settings.users.table.deactivate")}
              </>
            ) : (
              <>
                <UserCheck className="h-4 w-4" />
                {t("settings.users.table.activate")}
              </>
            )}
          </DropdownMenuItem>
        )}

        <DropdownMenuSeparator className="bg-muted" />

        {isSelf ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-2 py-1.5 text-sm text-muted-foreground flex items-center gap-2 cursor-not-allowed">
                  <Trash2 className="h-4 w-4" />
                  {t("settings.users.table.delete")}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {t("settings.users.table.cannotDeleteSelf")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <DropdownMenuItem
            onClick={() => onDelete(user)}
            className="gap-2 text-red-400 focus:bg-accent focus:text-red-400"
          >
            <Trash2 className="h-4 w-4" />
            {t("settings.users.table.delete")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function UserTable({
  users,
  currentUserId,
  onResetOtp,
  onSetCredentials,
  onToggleStatus,
  onToggleVoice,
  onDelete,
}: UserTableProps) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      {/* Desktop table */}
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-muted-foreground">{t("settings.users.table.user")}</TableHead>
              <TableHead className="text-muted-foreground max-w-[180px]">{t("settings.users.table.email")}</TableHead>
              <TableHead className="text-muted-foreground">{t("settings.users.table.role")}</TableHead>
              <TableHead className="text-muted-foreground">{t("settings.users.table.status")}</TableHead>
              <TableHead className="text-muted-foreground">{t("settings.users.table.voice")}</TableHead>
              <TableHead className="text-muted-foreground hidden lg:table-cell">{t("settings.users.table.created")}</TableHead>
              <TableHead className="text-muted-foreground text-right w-10">
                {t("settings.users.table.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              return (
                <TableRow
                  key={user.id}
                  className={`border-border hover:bg-accent/50 ${
                    !user.is_active ? "opacity-50" : ""
                  }`}
                >
                  <TableCell className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{user.username}</p>
                    {user.display_name && (
                      <p className="text-xs text-muted-foreground">{user.display_name}</p>
                    )}
                  </TableCell>
                  <TableCell className="max-w-[180px]">
                    <span className="block text-sm text-foreground truncate" title={user.email || undefined}>
                      {user.email || "--"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <RoleBadge role={user.role} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge isActive={user.is_active} />
                  </TableCell>
                  <TableCell>
                    <VoiceCell user={user} onToggleVoice={onToggleVoice} />
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm hidden lg:table-cell">
                    {formatDate(user.created_at)}
                  </TableCell>
                  <TableCell className="text-right w-10">
                    <UserActionMenu
                      user={user}
                      isSelf={isSelf}
                      onResetOtp={onResetOtp}
                      onSetCredentials={onSetCredentials}
                      onToggleStatus={onToggleStatus}
                      onDelete={onDelete}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Mobile card list */}
      <div className="md:hidden divide-y divide-border">
        {users.map((user) => {
          const isSelf = user.id === currentUserId;
          return (
            <div
              key={user.id}
              className={`p-4 space-y-2 ${!user.is_active ? "opacity-50" : ""}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {user.username}
                  </p>
                  {user.display_name && (
                    <p className="text-xs text-muted-foreground truncate">
                      {user.display_name}
                    </p>
                  )}
                </div>
                <UserActionMenu
                  user={user}
                  isSelf={isSelf}
                  onResetOtp={onResetOtp}
                  onSetCredentials={onSetCredentials}
                  onToggleStatus={onToggleStatus}
                  onDelete={onDelete}
                />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <RoleBadge role={user.role} />
                <StatusBadge isActive={user.is_active} />
              </div>
              {user.email && (
                <p className="text-xs text-muted-foreground truncate">{user.email}</p>
              )}
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">{t("settings.users.table.voice")}</span>
                <VoiceCell user={user} onToggleVoice={onToggleVoice} />
              </div>
              <p className="text-xs text-muted-foreground">
                {t("settings.users.table.createdMobile", { date: formatDate(user.created_at) })}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
