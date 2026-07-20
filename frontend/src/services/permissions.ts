import { fetchWithAuth } from "./fetchWithAuth";

const AUTH_BASE = "/api/auth";

/**
 * System-level permission flags (PROJ-65 `GET /api/auth/permissions`).
 *
 * The endpoint returns all `permissions_system` flags for the current user.
 * Only the flags consumed by the Settings UI (PROJ-66) are typed explicitly;
 * the index signature covers the remaining flags the endpoint also returns.
 */
export interface SystemPermissions {
  can_manage_users: boolean;
  can_manage_dms_folders: boolean;
  can_view_chat_archive: boolean;
  can_manage_mailboxes: boolean;
  [flag: string]: boolean;
}

/**
 * Fetches the current user's effective system permissions.
 *
 * A 401 is handled globally by `fetchWithAuth` (redirect to /login). Any other
 * non-OK status throws so the caller can fail open to the legacy admin check.
 */
export async function getPermissions(): Promise<SystemPermissions> {
  const res = await fetchWithAuth(`${AUTH_BASE}/permissions`);
  if (!res.ok) {
    throw new Error(`Berechtigungen konnten nicht geladen werden (${res.status}).`);
  }
  const body = await res.json();
  // Endpoint may wrap the flags in an array or a `permissions` key.
  if (Array.isArray(body)) return body[0] as SystemPermissions;
  if (body && typeof body === "object" && "permissions" in body) {
    return (body as { permissions: SystemPermissions }).permissions;
  }
  return body as SystemPermissions;
}
