"use client";

import { Bot, PanelLeftClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface SidebarHeaderProps {
  onCollapse: () => void;
}

export function SidebarHeader({ onCollapse }: SidebarHeaderProps) {
  return (
    <div className="flex items-center justify-between px-3 py-3 border-b border-gray-700">
      <div className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-blue-500" aria-hidden />
        <span className="font-semibold text-gray-100">Alice</span>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            onClick={onCollapse}
            className="h-7 w-7 text-gray-400 hover:text-gray-100 hover:bg-gray-700"
            aria-label="Sidebar einklappen"
          >
            <PanelLeftClose className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="right">Sidebar einklappen</TooltipContent>
      </Tooltip>
    </div>
  );
}
