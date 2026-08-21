import { WeaviateSchemasTile } from "./WeaviateSchemasTile";
import { GrafanaTile } from "./GrafanaTile";
import { N8nRunningTile } from "./N8nRunningTile";
import { N8nFailedTile } from "./N8nFailedTile";
import { ServicesTile } from "./ServicesTile";
import { DmsCoverageTile } from "./DmsCoverageTile";
import { DmsQualityWarningsTile } from "./DmsQualityWarningsTile";

/**
 * Central tile registry (PROJ-77 AC-H4/H5). Adding a tile means: create its
 * component file, then add one entry here — the grid, the other tiles, and
 * their data sources never need to change. Removing/swapping a tile touches
 * only its own entry + component file.
 */
export const DASHBOARD_TILES: { id: string; element: React.ReactNode }[] = [
  { id: "weaviate-schemas", element: <WeaviateSchemasTile /> },
  {
    id: "grafana-gpu",
    element: (
      <GrafanaTile
        title="GPU-Metriken"
        src="https://grafana.happy-mining.de/d/vlvPlrgnk/nvidia-gpu-metrics?orgId=1&from=now-30m&to=now&timezone=browser&var-job=nvidia&var-node=dcgm:9400&var-gpu=0&refresh=10s&kiosk"
      />
    ),
  },
  {
    id: "grafana-docker",
    element: (
      <GrafanaTile
        title="Docker & System Monitoring"
        src="https://grafana.happy-mining.de/d/77aa3684-7d80-48f1-b631-e6cf49b65305/docker-and-system-monitoring?var-interval=30s&orgId=1&from=now-24h&to=now&timezone=browser&var-containergroup=$__all&var-server=192.168.178.88&refresh=30s&kiosk"
      />
    ),
  },
  { id: "n8n-running", element: <N8nRunningTile /> },
  { id: "n8n-failed", element: <N8nFailedTile /> },
  { id: "services", element: <ServicesTile /> },
  { id: "dms-coverage", element: <DmsCoverageTile /> },
  { id: "dms-quality-warnings", element: <DmsQualityWarningsTile /> },
];
