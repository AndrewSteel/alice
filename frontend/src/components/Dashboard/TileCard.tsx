"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface TileCardProps {
  title: string;
  onRefresh?: () => void;
  refreshAriaLabel?: string;
  refreshing?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * Shared chrome for dashboard tiles (PROJ-77 AC-H1/H2): title bar with an
 * optional refresh action, sized to a comfortable phone-portrait width and
 * height-to-content. Each tile owns its own loading/empty/error body
 * (AC-H3) — this component only provides the card frame.
 */
export function TileCard({
  title,
  onRefresh,
  refreshAriaLabel,
  refreshing,
  children,
  className,
}: TileCardProps) {
  return (
    <Card className={cn("w-full sm:w-[380px] shrink-0", className)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 p-4 pb-2">
        <CardTitle className="text-base font-semibold">{title}</CardTitle>
        {onRefresh && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label={refreshAriaLabel}
          >
            <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-0">{children}</CardContent>
    </Card>
  );
}
