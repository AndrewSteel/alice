"use client";

import {
  Workflow,
  MessageSquare,
  Home,
  Hammer,
  KanbanSquare,
  NotebookPen,
  Upload,
  ExternalLink,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface ServiceLink {
  label: string;
  url: string;
  icon: LucideIcon;
  external: boolean;
}

const SERVICES: ServiceLink[] = [
  { label: "n8n", url: "https://n8n.happy-mining.de", icon: Workflow, external: true },
  { label: "Open WebUI", url: "https://openwebui.happy-mining.de", icon: MessageSquare, external: true },
  { label: "Home Assistant", url: "https://homeassistant.happy-mining.de", icon: Home, external: true },
  { label: "HA Development", url: "https://hassdev.happy-mining.de", icon: Hammer, external: true },
  { label: "Kanboard", url: "https://kanboard.happy-mining.de", icon: KanbanSquare, external: true },
  { label: "Jupyter", url: "https://jupyter.happy-mining.de", icon: NotebookPen, external: true },
  { label: "Finance Upload", url: "/finance_upload/index.html", icon: Upload, external: false },
];

interface ServiceLinksProps {
  onLinkClick?: () => void;
}

export function ServiceLinks({ onLinkClick }: ServiceLinksProps) {
  return (
    <div className="border-t border-gray-700 px-3 py-3">
      <p className="px-1 mb-2 text-xs font-medium text-gray-500 uppercase tracking-wider">
        Services
      </p>
      <nav aria-label="Externe Services" className="space-y-0.5">
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
              className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-gray-300 hover:bg-gray-700 hover:text-gray-100 transition-colors group"
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate flex-1">{service.label}</span>
              {service.external && (
                <ExternalLink
                  className="h-3 w-3 shrink-0 text-gray-600 group-hover:text-gray-400 transition-colors"
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
