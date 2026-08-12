"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TileCard } from "./TileCard";

// Grafana blocking embedding (X-Frame-Options/CSP) does not reliably raise a
// JS-observable error on a cross-origin iframe — the browser just renders a
// blank frame. A load-timeout is the practical way to detect that (AC-D3).
const EMBED_TIMEOUT_MS = 6000;

interface GrafanaTileProps {
  title: string;
  src: string;
}

export function GrafanaTile({ title, src }: GrafanaTileProps) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Runs once per mount (the iframe src is static — AC-D2 forbids Alice from
  // reloading it; Grafana's own `refresh` URL param handles live updates).
  useEffect(() => {
    timeoutRef.current = setTimeout(() => setFailed(true), EMBED_TIMEOUT_MS);
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const handleLoad = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
  }, []);

  const handleError = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setFailed(true);
  }, []);

  return (
    <TileCard title={title} className="sm:w-[420px]">
      {failed ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground">{t("dashboard.grafana.blockedError")}</p>
          <Button asChild variant="outline" size="sm">
            <a href={src} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-4 w-4 mr-1.5" />
              {t("dashboard.grafana.openInNewTab")}
            </a>
          </Button>
        </div>
      ) : (
        <iframe
          src={src}
          title={title}
          onLoad={handleLoad}
          onError={handleError}
          className="w-full h-[560px] rounded-md border border-border"
        />
      )}
    </TileCard>
  );
}
