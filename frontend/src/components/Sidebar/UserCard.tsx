"use client";

import { LogOut, Settings } from "lucide-react";
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
  const { user, logout } = useAuth();
  if (!user) return null;

  const initials = user.username.slice(0, 2).toUpperCase();

  return (
    <div className="border-t border-gray-700 px-3 py-3">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex items-center gap-2.5 w-full rounded-md px-2 py-1.5 hover:bg-gray-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
            <Avatar className="h-8 w-8 bg-blue-600 shrink-0">
              <AvatarFallback className="bg-blue-600 text-white text-xs font-semibold">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col items-start min-w-0">
              <span className="text-sm font-medium text-gray-100 truncate">{user.username}</span>
              <span className="text-xs text-gray-400 capitalize">{user.role}</span>
            </div>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-48 bg-gray-800 border-gray-700">
          <DropdownMenuItem className="gap-2 text-gray-300 focus:text-gray-100 focus:bg-gray-700 cursor-pointer">
            <Settings className="h-4 w-4" aria-hidden />
            Einstellungen
          </DropdownMenuItem>
          <DropdownMenuSeparator className="bg-gray-700" />
          <DropdownMenuItem
            onClick={logout}
            className="gap-2 text-red-400 focus:text-red-300 focus:bg-gray-700 cursor-pointer"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Abmelden
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
