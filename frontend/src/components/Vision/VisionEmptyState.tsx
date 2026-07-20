"use client";

import { LayoutGrid } from "lucide-react";
import { useTranslation } from "react-i18next";

export function VisionEmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12">
      <LayoutGrid className="w-12 h-12 text-muted-foreground mb-4" />
      <p className="text-muted-foreground text-sm">{t("vision.noMatches")}</p>
    </div>
  );
}
