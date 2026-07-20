"use client";

import {
  Workflow,
  MessageSquare,
  Home,
  ChartNoAxesCombined,
  KanbanSquare,
  NotebookPen,
  Upload,
  ExternalLink,
  HardDrive,
  Server,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

interface ServiceLink {
  label: string;
  url: string;
  icon: LucideIcon;
  external: boolean;
}

const SERVICES: ServiceLink[] = [
  {
    label: "n8n",
    url: "https://n8n.happy-mining.de",
    icon: Workflow,
    external: true,
  },
  {
    label: "Open WebUI",
    url: "https://openwebui.happy-mining.de",
    icon: MessageSquare,
    external: true,
  },
  {
    label: "Home Assistant",
    url: "http://homeassistant.lan:8123",
    icon: Home,
    external: true,
  },
  {
    label: "Storage",
    url: "http://storage.lan:5000",
    icon: HardDrive,
    external: true,
  },
  {
    label: "Knox",
    url: "http://knox.lan:5000",
    icon: HardDrive,
    external: true,
  },
  {
    label: "Grafana",
    url: "http://grafana.lan:3000",
    icon: ChartNoAxesCombined,
    external: true,
  },
  {
    label: "PVE",
    url: "http://pve.lan:8006",
    icon: Server,
    external: true,
  },
  {
    label: "Kanboard",
    url: "https://kanboard.happy-mining.de",
    icon: KanbanSquare,
    external: true,
  },
  {
    label: "Jupyter",
    url: "https://jupyter.happy-mining.de",
    icon: NotebookPen,
    external: true,
  },
  {
    label: "Finance Upload",
    url: "/finance_upload/index.html",
    icon: Upload,
    external: false,
  },
];

interface ServiceLinksProps {
  onLinkClick?: () => void;
}

export function ServiceLinks({ onLinkClick }: ServiceLinksProps) {
  const { t } = useTranslation();
  return (
    <div className="border-t border-border px-3 py-3">
      <p className="px-1 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
        {t("sidebar.services.title")}
      </p>
      <nav aria-label={t("sidebar.services.ariaLabel")} className="space-y-0.5">
        {SERVICES.map((service) => {
          const Icon = service.icon;
          return (
            <a
              key={service.label}
              href={service.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={service.label}
              onClick={onLinkClick}
              className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent hover:text-foreground transition-colors group"
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate flex-1">{service.label}</span>
              {service.external && (
                <ExternalLink
                  className="h-3 w-3 shrink-0 text-muted-foreground group-hover:text-muted-foreground transition-colors"
                  aria-hidden="true"
                />
              )}
            </a>
          );
        })}
      </nav>
    </div>
  );
}
