import { fetchWithAuth } from "./fetchWithAuth";

// PROJ-122: admin interface to the new ETL (alice-etl-status behind nginx /api/etl/).
// Reasons and error messages from the register / PROJ-120 are passed through unchanged.

const ETL_BASE = "/api/etl";

export const ETL_KINDS = ["document", "image", "email", "audio", "video"] as const;
export const ETL_STATES = ["pending", "running", "done", "failed", "failed_permanent", "skipped"] as const;
export type EtlKind = (typeof ETL_KINDS)[number];
export type EtlState = (typeof ETL_STATES)[number];

export class EtlError extends Error {
  status: number;
  code: string;
  service?: string;
  body: Record<string, unknown>;
  constructor(status: number, body: Record<string, unknown>) {
    super(String(body.detail ?? body.error ?? status));
    this.status = status;
    this.code = String(body.error ?? (status === 0 ? "network" : "error"));
    this.service = body.service as string | undefined;
    this.body = body;
  }
}

async function request<T>(path: string, init: RequestInit = {}, params?: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = `${ETL_BASE}${path}${qs.toString() ? `?${qs.toString()}` : ""}`;
  let res: Response;
  try {
    res = await fetchWithAuth(url, init);
  } catch (e) {
    if (e instanceof Error && /Session|authentication/i.test(e.message)) throw e;
    throw new EtlError(0, { error: "network" });
  }
  let body: Record<string, unknown> = {};
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  if (!res.ok) throw new EtlError(res.status, body);
  return body as T;
}

// ---------------------------------------------------------------- types
export interface RebuildProgress {
  id: number;
  start_stage?: string;
  kind?: string | null;
  status: "running" | "paused" | "waiting" | "done" | "cancelled";
  reason?: string | null;
  started_by?: string;
  started_at?: string;
  finished_at?: string | null;
  total?: number;
  excluded?: Record<string, number>;
  excluded_total?: number;
  in_run?: number;
  released?: number;
  finished?: number;
  stages?: Record<string, { sources: number; done: number; failed: number; running: number; open: number }>;
  throughput_per_hour?: number;
  remaining_seconds?: number | null;
  reconcile_id?: number | null;
  as_of?: string;
}

export interface ReconcileLevel {
  gaps?: number;
  repaired?: number;
  reported?: number;
  repair_failed?: number;
  by_gap?: Record<string, number>;
}

export interface ReconcileResult {
  id: number;
  kind: "nightly" | "on_demand" | "after_rebuild";
  mode?: "levels" | "full_rehash";
  rebuild_run_id?: number | null;
  state: "running" | "complete" | "incomplete";
  reason?: string | null;
  guard_triggered?: boolean;
  started_at: string;
  finished_at?: string | null;
  duration_seconds?: number | null;
  summary?: {
    levels?: Record<string, ReconcileLevel>;
    skipped_folders?: { folder: string; reason: string }[];
    hash_cycle?: Record<string, unknown> | null;
    notes?: string[];
    gap_list_truncated?: Record<string, number>;
  };
}

export interface EtlStateResponse {
  as_of: string;
  user: string;
  services: { register: boolean; rebuild: boolean };
  retry_limit: number;
  stages: string[];
  matrix: Record<string, Record<EtlState, number>>;
  counts: { sources: number; deleted: number; locked: number; failed_permanent: number; serious: number; failed: number };
  rebuild: { run: RebuildProgress | null; active: boolean; percent: number | null } | null;
  reconcile: { last: ReconcileResult | null; running: number | null; attention: boolean; reported_gaps: number } | null;
  light: "green" | "yellow" | "red" | null;
}

export interface SourceListItem {
  id: string;
  title: string;
  kind: EtlKind;
  deleted: boolean;
  locked: boolean;
  stage: string;
  state: EtlState;
  attempts: number;
  error: string | null;
  error_truncated: boolean | null;
  last_attempt_at: string | null;
  next_retry_at: string | null;
}

export interface ErrorItem {
  id: string;
  title: string;
  kind: EtlKind;
  stage: string | null;
  state: "failed" | "failed_permanent" | "locked";
  attempts: number | null;
  error: string | null;
  error_truncated: boolean | null;
  error_at: string | null;
  next_retry_at: string | null;
  locked: boolean;
}

export interface Page<T> {
  total: number;
  items: T[];
  retryable?: number;
}

export interface SourceDetail {
  id: string;
  title: string;
  kind: EtlKind;
  type: string | null;
  hash: string;
  size: number | null;
  path: string;
  deleted: boolean;
  deleted_at: string | null;
  locked: boolean;
  repo_error: string | null;
  repo_error_at: string | null;
  stages: {
    stage: string;
    state: EtlState;
    attempts: number;
    error: string | null;
    last_attempt_at: string | null;
    next_retry_at: string | null;
    retryable: boolean;
  }[];
  locations: {
    path: string | null;
    mailbox: string | null;
    message_id: string | null;
    present: boolean;
    first_seen: string;
    last_seen: string;
    gone_at: string | null;
  }[];
  events: { level: string; event: string; message: string; created_at: string }[];
}

export interface SourceFilter {
  stage: string;
  state?: EtlState | "";
  kind?: EtlKind | "";
  deleted?: "no" | "yes" | "all";
  locked?: "all" | "yes" | "no";
  q?: string;
}

export interface ErrorFilter {
  stage?: string;
  state?: "failed" | "failed_permanent" | "locked" | "";
  kind?: EtlKind | "";
}

export interface BulkResult {
  sources: number;
  limit: number;
  allowed?: boolean;
  stages?: number;
  skipped?: number;
}

export interface RebuildPreview {
  start_stage: string;
  kind: string | null;
  sources: number;
  stages: string[];
}

export interface ReconcileGap {
  level: number;
  gap: string;
  source_id: string | null;
  path: string | null;
  detail: string | null;
  action: "repaired" | "reported" | "repair_failed";
}

export interface RunErrorItem {
  id: string;
  title: string;
  stage: string;
  state?: string;
  error: string | null;
}

// ---------------------------------------------------------------- calls
const clean = <T extends object>(f: T) =>
  Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined && v !== null && v !== ""));

export const etlApi = {
  state: (kind?: string, includeDeleted?: boolean) =>
    request<EtlStateResponse>("/state", {}, { kind, include_deleted: includeDeleted ? "true" : undefined }),
  sources: (f: SourceFilter, limit: number, offset: number) =>
    request<Page<SourceListItem>>("/sources", {}, { ...clean(f), limit, offset }),
  errors: (f: ErrorFilter, limit: number, offset: number) =>
    request<Page<ErrorItem>>("/errors", {}, { ...clean(f), limit, offset }),
  source: (id: string) => request<SourceDetail>(`/sources/${encodeURIComponent(id)}`),
  retry: (id: string, stage: string) =>
    request<{ state: string }>(`/sources/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}/retry`, {
      method: "POST",
    }),
  bulkRetry: (scope: "sources" | "errors", filter: SourceFilter | ErrorFilter, dryRun: boolean) =>
    request<BulkResult>("/retry", {
      method: "POST",
      body: JSON.stringify({ scope, filter: clean(filter), dry_run: dryRun }),
    }),
  preview: (startStage: string, kind?: string) =>
    request<RebuildPreview>("/rebuild/preview", {}, { start_stage: startStage, kind }),
  startRebuild: (startStage: string, kind?: string) =>
    request<RebuildProgress>("/rebuilds", {
      method: "POST",
      body: JSON.stringify({ start_stage: startStage, kind: kind || null }),
    }),
  rebuilds: (limit: number, offset: number) => request<Page<RebuildProgress>>("/rebuilds", {}, { limit, offset }),
  control: (id: number, action: "pause" | "resume" | "cancel") =>
    request<RebuildProgress>(`/rebuilds/${id}/${action}`, { method: "POST" }),
  runErrors: (id: number, limit: number, offset: number) =>
    request<Page<RunErrorItem>>(`/rebuilds/${id}/errors`, {}, { limit, offset }),
  reconcileNow: () => request<{ id: number }>("/reconcile", { method: "POST" }),
  fullRehash: () => request<{ id: number }>("/reconcile/full-rehash", { method: "POST" }),
  results: (limit: number, offset: number) =>
    request<Page<ReconcileResult>>("/reconcile/results", {}, { limit, offset }),
  result: (id: number) => request<ReconcileResult>(`/reconcile/results/${id}`),
  gaps: (id: number, level: number, limit: number, offset: number) =>
    request<Page<ReconcileGap>>(`/reconcile/results/${id}/gaps`, {}, { level, limit, offset }),
};
