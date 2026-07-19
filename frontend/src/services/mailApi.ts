import { fetchWithAuth } from "./fetchWithAuth";

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
  const res = await fetchWithAuth(`${BASE}/mailboxes`);
  if (!res.ok) throw new Error(`Fehler beim Laden der Postfächer (${res.status}).`);
  const body = await res.json();
  return unwrapBody<Mailbox>(body, "mailboxes");
}

export async function createMailbox(data: CreateMailboxInput): Promise<CreateMailboxResult> {
  const res = await fetchWithAuth(`${BASE}/mailboxes`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (res.status === 400) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || "Ungültige Eingabe.");
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
  const body = await res.json();
  const item = Array.isArray(body) && body.length > 0 ? body[0] : body;
  return item as CreateMailboxResult;
}

export async function updateMailbox(data: UpdateMailboxInput): Promise<Mailbox> {
  const res = await fetchWithAuth(`${BASE}/mailboxes`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  if (res.status === 400 || res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
  const body = await res.json();
  return (Array.isArray(body) ? body[0] : body) as Mailbox;
}

export async function deleteMailbox(id: string): Promise<void> {
  const res = await fetchWithAuth(`${BASE}/mailboxes`, {
    method: "DELETE",
    body: JSON.stringify({ id }),
  });
  if (res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
}

export async function getMailboxAccess(mailboxId: string): Promise<AccessListUser[]> {
  const res = await fetchWithAuth(`${BASE}/mailboxes/access?id=${encodeURIComponent(mailboxId)}`);
  if (!res.ok) throw new Error(`Fehler beim Laden der Zugriffsrechte (${res.status}).`);
  const body = await res.json();
  return unwrapBody<AccessListUser>(body, "users");
}

export async function updateMailboxAccess(mailboxId: string, userIds: string[]): Promise<void> {
  const res = await fetchWithAuth(`${BASE}/mailboxes/access`, {
    method: "PUT",
    body: JSON.stringify({ mailbox_id: mailboxId, user_ids: userIds }),
  });
  if (res.status === 403 || res.status === 404) {
    const b = await res.json().catch(() => ({})) as Record<string, string>;
    throw new Error(b.error || `Fehler (${res.status}).`);
  }
  if (!res.ok) throw new Error(`Serverfehler (${res.status}).`);
}

export async function getAllUsers(): Promise<AliceUser[]> {
  const res = await fetchWithAuth(`${BASE}/users`);
  if (!res.ok) throw new Error(`Fehler beim Laden der Nutzer (${res.status}).`);
  const body = await res.json();
  return unwrapBody<AliceUser>(body, "users");
}
