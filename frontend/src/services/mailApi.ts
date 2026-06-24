import { clearToken, getToken } from "./auth";

const BASE = "/api/webhook/alice";

// ---------- Types ----------

export interface MailboxAccessUser {
  user_id: string;
  display_name: string;
  username: string;
}

export interface Mailbox {
  id: string;
  owner_id: string;
  owner_name: string;
  display_name: string;
  imap_host: string;
  imap_port: number;
  imap_username: string;
  ssl_enabled: boolean;
  sync_interval: number;
  start_date: string | null;
  status: "active" | "syncing" | "error" | "unclassified";
  mails_indexed: number;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string;
  access_users: MailboxAccessUser[];
}

export interface AccessListUser {
  user_id: string;
  display_name: string;
  username: string;
  has_access: boolean;
}

export interface AliceUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
}

export interface CreateMailboxInput {
  display_name: string;
  imap_host: string;
  imap_port: number;
  imap_username: string;
  password: string;
  ssl_enabled: boolean;
  sync_interval: number;
  start_date?: string | null;
}

export interface UpdateMailboxInput {
  id: string;
  display_name?: string;
  imap_host?: string;
  imap_port?: number;
  imap_username?: string;
  password?: string;
  ssl_enabled?: boolean;
  sync_interval?: number;
  start_date?: string | null;
}

export interface CreateMailboxResult {
  mailbox: Mailbox;
  connection_test: { ok: boolean; message: string };
}

// ---------- Helpers ----------

function authHeaders(): HeadersInit {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    throw new Error("No authentication token");
  }
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

function handleAuth(res: Response) {
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen — bitte erneut anmelden.");
  }
}

function unwrapBody<T>(body: unknown, key: string): T[] {
  if (Array.isArray(body) && body.length > 0 && Array.isArray((body[0] as Record<string, unknown>)[key])) {
    return (body[0] as Record<string, unknown>)[key] as T[];
  }
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object" && Array.isArray((body as Record<string, unknown>)[key])) {
    return (body as Record<string, unknown>)[key] as T[];
  }
  return [];
}

function unwrapSingle<T>(body: unknown, key: string): T {
  if (Array.isArray(body) && body.length > 0) {
    const first = body[0] as Record<string, unknown>;
    return (key in first ? first[key] : first) as T;
  }
  if (body && typeof body === "object" && key in (body as Record<string, unknown>)) {
    return (body as Record<string, unknown>)[key] as T;
  }
  return body as T;
}

// ---------- API ----------

export async function getMailboxes(): Promise<Mailbox[]> {
  const res = await fetch(`${BASE}/mailboxes`, { headers: authHeaders() });
  handleAuth(res);
  if (!res.ok) throw new Error(`Fehler beim Laden der Postfächer (${res.status}).`);
  const body = await res.json();
  return unwrapBody<Mailbox>(body, "mailboxes");
}

export async function createMailbox(data: CreateMailboxInput): Promise<CreateMailboxResult> {
  const res = await fetch(`${BASE}/mailboxes`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  handleAuth(res);
  if (res.status === 400) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || "Ungültige Eingabe.");
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
  const body = await res.json();
  return unwrapSingle<CreateMailboxResult>(body, "mailbox") as unknown as CreateMailboxResult;
}

export async function updateMailbox(data: UpdateMailboxInput): Promise<Mailbox> {
  const res = await fetch(`${BASE}/mailboxes`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  handleAuth(res);
  if (res.status === 400 || res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
  const body = await res.json();
  return (Array.isArray(body) ? body[0] : body) as Mailbox;
}

export async function deleteMailbox(id: string): Promise<void> {
  const res = await fetch(`${BASE}/mailboxes`, {
    method: "DELETE",
    headers: authHeaders(),
    body: JSON.stringify({ id }),
  });
  handleAuth(res);
  if (res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
}

export async function getMailboxAccess(mailboxId: string): Promise<AccessListUser[]> {
  const res = await fetch(`${BASE}/mailboxes/access?id=${encodeURIComponent(mailboxId)}`, {
    headers: authHeaders(),
  });
  handleAuth(res);
  if (!res.ok) throw new Error(`Fehler beim Laden der Zugriffsrechte (${res.status}).`);
  const body = await res.json();
  return unwrapBody<AccessListUser>(body, "users");
}

export async function updateMailboxAccess(mailboxId: string, userIds: string[]): Promise<void> {
  const res = await fetch(`${BASE}/mailboxes/access`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify({ mailbox_id: mailboxId, user_ids: userIds }),
  });
  handleAuth(res);
  if (res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
}

export async function getAllUsers(): Promise<AliceUser[]> {
  const res = await fetch(`${BASE}/users`, { headers: authHeaders() });
  handleAuth(res);
  if (!res.ok) throw new Error(`Fehler beim Laden der Nutzer (${res.status}).`);
  const body = await res.json();
  return unwrapBody<AliceUser>(body, "users");
}
