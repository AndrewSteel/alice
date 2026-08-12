import { STREAM_API_URL } from "./api";
import { fetchWithAuth } from "./fetchWithAuth";

// Admin dashboard data sources (PROJ-77) — Weaviate schema overview and n8n
// execution monitoring, served by alice-chat-stream's /admin/* endpoints.

export interface WeaviateSchema {
  name: string;
  count: number;
}

export interface N8nExecutionsResponse<T> {
  executions: T[];
  extra_count: number;
  overview_url: string;
}

export interface N8nRunningExecution {
  id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
  url: string;
}

export interface N8nFailedExecution {
  id: string;
  workflow_id: string;
  workflow_name: string;
  failed_at: string;
  url: string;
}

export async function fetchWeaviateSchemas(): Promise<WeaviateSchema[]> {
  if (!STREAM_API_URL) throw new Error("STREAM_API_URL nicht konfiguriert");
  let res: Response;
  try {
    res = await fetchWithAuth(`${STREAM_API_URL}/admin/weaviate/schemas`, {
      method: "GET",
    });
  } catch {
    throw new Error("Netzwerkfehler -- Weaviate-Schemas konnten nicht geladen werden.");
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status})`);
  const data = await res.json();
  return data.schemas ?? [];
}

export async function fetchRunningN8nExecutions(): Promise<N8nExecutionsResponse<N8nRunningExecution>> {
  if (!STREAM_API_URL) throw new Error("STREAM_API_URL nicht konfiguriert");
  let res: Response;
  try {
    res = await fetchWithAuth(`${STREAM_API_URL}/admin/n8n/executions/running`, {
      method: "GET",
    });
  } catch {
    throw new Error("Netzwerkfehler -- n8n-Prozesse konnten nicht geladen werden.");
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status})`);
  return res.json();
}

export async function fetchFailedN8nExecutions(): Promise<N8nExecutionsResponse<N8nFailedExecution>> {
  if (!STREAM_API_URL) throw new Error("STREAM_API_URL nicht konfiguriert");
  let res: Response;
  try {
    res = await fetchWithAuth(`${STREAM_API_URL}/admin/n8n/executions/failed`, {
      method: "GET",
    });
  } catch {
    throw new Error("Netzwerkfehler -- n8n-Prozesse konnten nicht geladen werden.");
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status})`);
  return res.json();
}
