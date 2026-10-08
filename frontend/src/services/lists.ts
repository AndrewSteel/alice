import { fetchWithAuth } from "./fetchWithAuth";

// PROJ-106 — Aufgaben & Listen. Only the admin role config lives in the UI for
// now; lists and entries are used via chat/voice (WebApp view → PROJ-107).

const LISTS_BASE = "/api/lists";

export type ListsRole = "admin" | "user" | "guest" | "child";

export interface ListsRoleFlag {
  role: ListsRole;
  can_use_lists: boolean;
}

async function detail(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

export async function getListsRoles(): Promise<ListsRoleFlag[]> {
  const res = await fetchWithAuth(`${LISTS_BASE}/admin/roles`, { method: "GET" });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()).roles;
}

export async function updateListsRoles(roles: ListsRoleFlag[]): Promise<ListsRoleFlag[]> {
  const res = await fetchWithAuth(`${LISTS_BASE}/admin/roles`, {
    method: "PUT",
    body: JSON.stringify({ roles }),
  });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()).roles;
}
