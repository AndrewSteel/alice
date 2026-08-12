"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TileCard } from "./TileCard";
import { fetchWeaviateSchemas, WeaviateSchema } from "@/services/dashboardApi";

export function WeaviateSchemasTile() {
  const { t } = useTranslation();
  const [schemas, setSchemas] = useState<WeaviateSchema[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchWeaviateSchemas()
      .then((data) => setSchemas(data))
      .catch(() => setError(t("dashboard.weaviate.error")))
      .finally(() => setLoading(false));
  }, [t]);

  // AC-C2: load once on mount — no polling, only the manual refresh button re-fetches.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <TileCard
      title={t("dashboard.weaviate.title")}
      onRefresh={load}
      refreshAriaLabel={t("dashboard.weaviate.refreshAria")}
      refreshing={loading}
    >
      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-2/3" />
        </div>
      )}

      {!loading && error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!loading && !error && schemas && schemas.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("dashboard.weaviate.empty")}</p>
      )}

      {!loading && !error && schemas && schemas.length > 0 && (
        <ul className="space-y-1.5">
          {schemas.map((s) => (
            <li key={s.name} className="flex items-center justify-between text-sm">
              <span className="text-foreground truncate">{s.name}</span>
              <Badge variant="secondary">
                {t("dashboard.weaviate.records", { count: s.count })}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </TileCard>
  );
}
