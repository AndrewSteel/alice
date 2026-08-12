"use client";

import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TileCard } from "./TileCard";
import { SERVICES } from "@/components/Sidebar/ServiceLinks";

// AC-G1/G2: identical service list + link behavior as the existing Sidebar.
export function ServicesTile() {
  const { t } = useTranslation();

  return (
    <TileCard title={t("dashboard.services.title")}>
      <div className="flex flex-wrap gap-2">
        {SERVICES.map((service) => {
          const Icon = service.icon;
          return (
            <a
              key={service.label}
              href={service.url}
              target={service.external ? "_blank" : undefined}
              rel={service.external ? "noopener noreferrer" : undefined}
            >
              <Badge variant="secondary" className="gap-1.5 font-normal cursor-pointer hover:bg-secondary/80">
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {service.label}
                {service.external && <ExternalLink className="h-3 w-3" aria-hidden="true" />}
              </Badge>
            </a>
          );
        })}
      </div>
    </TileCard>
  );
}
