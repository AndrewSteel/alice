"use client";

import { LogOut, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/useAuth";

export function UserCard() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  if (!user) return null;

  const initials = user.username.slice(0, 2).toUpperCase();

  return (
    <div className="border-t border-border px-3 py-3">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex items-center gap-2.5 w-full rounded-md px-2 py-1.5 hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
            <Avatar className="h-8 w-8 bg-blue-600 shrink-0">
              <AvatarFallback className="bg-blue-600 text-white text-xs font-semibold">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col items-start min-w-0">
              <span className="text-sm font-medium text-foreground truncate">{user.username}</span>
              <span className="text-xs text-muted-foreground capitalize">{user.role}</span>
            </div>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-48 bg-card border-border">
          <DropdownMenuItem
            onClick={() => { window.location.href = "/settings"; }}
            className="gap-2 text-foreground focus:text-foreground focus:bg-accent cursor-pointer"
          >
            <Settings className="h-4 w-4" aria-hidden />
            {t("sidebar.userCard.settings")}
          </DropdownMenuItem>
          <DropdownMenuSeparator className="bg-muted" />
          <DropdownMenuItem
            onClick={logout}
            className="gap-2 text-red-400 focus:text-red-300 focus:bg-accent cursor-pointer"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            {t("sidebar.userCard.logout")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
