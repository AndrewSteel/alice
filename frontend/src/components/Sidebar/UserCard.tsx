"use client";

import { LayoutDashboard, LogOut, MessageSquare, Settings } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
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

interface UserCardProps {
  /** "sidebar" (default) = bottom bar in the Chat sidebar. "header" = compact, for the Dashboard's slim top bar (PROJ-77). */
  variant?: "sidebar" | "header";
}

export function UserCard({ variant = "sidebar" }: UserCardProps) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  if (!user) return null;

  const initials = user.username.slice(0, 2).toUpperCase();

  // PROJ-77: admins can switch between Dashboard and Chat from either view's
  // user menu — whichever view isn't the current one.
  const isAdmin = user.role === "admin";
  const onDashboard = pathname === "/dashboard";
  const viewToggle = isAdmin
    ? onDashboard
      ? { href: "/", label: t("sidebar.userCard.chat"), icon: MessageSquare }
      : { href: "/dashboard", label: t("sidebar.userCard.dashboard"), icon: LayoutDashboard }
    : null;

  const trigger = (
    <button
      className={
        variant === "header"
          ? "flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          : "flex items-center gap-2.5 w-full rounded-md px-2 py-1.5 hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      }
    >
      <Avatar className="h-8 w-8 bg-blue-600 shrink-0">
        <AvatarFallback className="bg-blue-600 text-white text-xs font-semibold">
          {initials}
        </AvatarFallback>
      </Avatar>
      {/* AC-A6: name + role stay reachable in both placements — just not
          forced to full sidebar width in the compact header variant. */}
      <div className="flex flex-col items-start min-w-0">
        <span className="text-sm font-medium text-foreground truncate">{user.username}</span>
        <span className="text-xs text-muted-foreground capitalize">{user.role}</span>
      </div>
    </button>
  );

  const menu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent side={variant === "header" ? "bottom" : "top"} align="end" className="w-48 bg-card border-border">
        <DropdownMenuItem
          onClick={() => { window.location.href = "/settings"; }}
          className="gap-2 text-foreground focus:text-foreground focus:bg-accent cursor-pointer"
        >
          <Settings className="h-4 w-4" aria-hidden />
          {t("sidebar.userCard.settings")}
        </DropdownMenuItem>
        {viewToggle && (
          <DropdownMenuItem
            // Client-side navigation (not a full reload): both routes share
            // the (main) layout, so this keeps the in-flight chat/vision
            // state alive and avoids re-triggering the once-per-load landing
            // redirect (which would otherwise bounce an admin straight back
            // to /dashboard on every "Chat" click).
            onClick={() => router.push(viewToggle.href)}
            className="gap-2 text-foreground focus:text-foreground focus:bg-accent cursor-pointer"
          >
            <viewToggle.icon className="h-4 w-4" aria-hidden />
            {viewToggle.label}
          </DropdownMenuItem>
        )}
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
  );

  if (variant === "header") return menu;

  return <div className="border-t border-border px-3 py-3">{menu}</div>;
}
