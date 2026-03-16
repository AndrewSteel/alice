"use client";

import { MoreVertical, KeyRound, UserX, UserCheck, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  onToggleStatus: (user: AdminUser) => void;
  onDelete: (user: AdminUser) => void;
}

function formatDate(dateStr: string): string {
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

function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    admin: "bg-purple-900/40 text-purple-300 border-purple-800",
    user: "bg-blue-900/40 text-blue-300 border-blue-800",
    guest: "bg-gray-700/40 text-gray-300 border-gray-600",
    child: "bg-green-900/40 text-green-300 border-green-800",
  };

  return (
    <Badge
      variant="secondary"
      className={`text-xs ${styles[role] || "bg-gray-700/40 text-gray-300 border-gray-600"}`}
    >
      {role}
    </Badge>
  );
}

function StatusBadge({ isActive }: { isActive: boolean }) {
  if (isActive) {
    return (
      <Badge
        variant="secondary"
        className="text-xs bg-emerald-900/40 text-emerald-300 border-emerald-800"
      >
        Aktiv
      </Badge>
    );
  }
  return (
    <Badge
      variant="secondary"
      className="text-xs bg-red-900/40 text-red-300 border-red-800"
    >
      Inaktiv
    </Badge>
  );
}

function UserActionMenu({
  user,
  isSelf,
  onResetOtp,
  onToggleStatus,
  onDelete,
}: {
  user: AdminUser;
  isSelf: boolean;
  onResetOtp: (user: AdminUser) => void;
  onToggleStatus: (user: AdminUser) => void;
  onDelete: (user: AdminUser) => void;
}) {
  const hasEmail = !!user.email;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-gray-400 hover:text-gray-100"
          aria-label={`Aktionen fuer ${user.username}`}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="bg-gray-800 border-gray-700 text-gray-100"
      >
        {hasEmail ? (
          <DropdownMenuItem
            onClick={() => onResetOtp(user)}
            className="gap-2 focus:bg-gray-700 focus:text-gray-100"
          >
            <KeyRound className="h-4 w-4" />
            OTP zuruecksetzen
          </DropdownMenuItem>
        ) : (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-2 py-1.5 text-sm text-gray-500 flex items-center gap-2 cursor-not-allowed">
                  <KeyRound className="h-4 w-4" />
                  OTP zuruecksetzen
                </div>
              </TooltipTrigger>
              <TooltipContent>
                Keine E-Mail-Adresse hinterlegt
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        <DropdownMenuSeparator className="bg-gray-700" />

        {isSelf ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-2 py-1.5 text-sm text-gray-500 flex items-center gap-2 cursor-not-allowed">
                  {user.is_active ? (
                    <UserX className="h-4 w-4" />
                  ) : (
                    <UserCheck className="h-4 w-4" />
                  )}
                  {user.is_active ? "Deaktivieren" : "Aktivieren"}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                Eigenen Account kann man nicht deaktivieren
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <DropdownMenuItem
            onClick={() => onToggleStatus(user)}
            className="gap-2 focus:bg-gray-700 focus:text-gray-100"
          >
            {user.is_active ? (
              <>
                <UserX className="h-4 w-4" />
                Deaktivieren
              </>
            ) : (
              <>
                <UserCheck className="h-4 w-4" />
                Aktivieren
              </>
            )}
          </DropdownMenuItem>
        )}

        <DropdownMenuSeparator className="bg-gray-700" />

        {isSelf ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="px-2 py-1.5 text-sm text-gray-500 flex items-center gap-2 cursor-not-allowed">
                  <Trash2 className="h-4 w-4" />
                  Loeschen
                </div>
              </TooltipTrigger>
              <TooltipContent>
                Eigenen Account kann man nicht loeschen
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <DropdownMenuItem
            onClick={() => onDelete(user)}
            className="gap-2 text-red-400 focus:bg-gray-700 focus:text-red-400"
          >
            <Trash2 className="h-4 w-4" />
            Loeschen
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
  onToggleStatus,
  onDelete,
}: UserTableProps) {
  return (
    <div className="rounded-lg border border-gray-700 overflow-hidden">
      {/* Desktop table */}
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow className="border-gray-700 hover:bg-transparent">
              <TableHead className="text-gray-400">Nutzer</TableHead>
              <TableHead className="text-gray-400 max-w-[180px]">E-Mail</TableHead>
              <TableHead className="text-gray-400">Rolle</TableHead>
              <TableHead className="text-gray-400">Status</TableHead>
              <TableHead className="text-gray-400 hidden lg:table-cell">Erstellt</TableHead>
              <TableHead className="text-gray-400 text-right w-10">
                Aktionen
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              return (
                <TableRow
                  key={user.id}
                  className={`border-gray-700 hover:bg-gray-800/50 ${
                    !user.is_active ? "opacity-50" : ""
                  }`}
                >
                  <TableCell className="min-w-0">
                    <p className="text-sm font-medium text-gray-100">{user.username}</p>
                    {user.display_name && (
                      <p className="text-xs text-gray-400">{user.display_name}</p>
                    )}
                  </TableCell>
                  <TableCell className="max-w-[180px]">
                    <span className="block text-sm text-gray-300 truncate" title={user.email || undefined}>
                      {user.email || "--"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <RoleBadge role={user.role} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge isActive={user.is_active} />
                  </TableCell>
                  <TableCell className="text-gray-400 text-sm hidden lg:table-cell">
                    {formatDate(user.created_at)}
                  </TableCell>
                  <TableCell className="text-right w-10">
                    <UserActionMenu
                      user={user}
                      isSelf={isSelf}
                      onResetOtp={onResetOtp}
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
      <div className="md:hidden divide-y divide-gray-700">
        {users.map((user) => {
          const isSelf = user.id === currentUserId;
          return (
            <div
              key={user.id}
              className={`p-4 space-y-2 ${!user.is_active ? "opacity-50" : ""}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-100 truncate">
                    {user.username}
                  </p>
                  {user.display_name && (
                    <p className="text-xs text-gray-400 truncate">
                      {user.display_name}
                    </p>
                  )}
                </div>
                <UserActionMenu
                  user={user}
                  isSelf={isSelf}
                  onResetOtp={onResetOtp}
                  onToggleStatus={onToggleStatus}
                  onDelete={onDelete}
                />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <RoleBadge role={user.role} />
                <StatusBadge isActive={user.is_active} />
              </div>
              {user.email && (
                <p className="text-xs text-gray-400 truncate">{user.email}</p>
              )}
              <p className="text-xs text-gray-500">
                Erstellt: {formatDate(user.created_at)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
