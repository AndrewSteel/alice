import { clearToken, getToken } from "./auth";

export interface FetchWithAuthOptions {
  /**
   * When true, a 401 response is returned to the caller as-is instead of
   * triggering clearToken() + redirect to /login. Used by callers where a
   * 401 does not necessarily mean an expired session (e.g. the voluntary
   * password change, where 401 can also mean "wrong current password").
   */
  suppressAuthRedirect?: boolean;
}

/**
 * Central authenticated fetch wrapper (PROJ-67).
 *
 * Consolidates the auth-header creation and 401 handling that was previously
 * duplicated across every service file.
 *
 * - Attaches `Authorization: Bearer <token>` and, unless the body is FormData
 *   or a Content-Type is already set, `Content-Type: application/json`.
 * - No token in storage -> redirect to /login before any request is sent.
 * - 401 response -> clearToken() + redirect to /login (unless suppressed).
 *
 * Returns the raw Response so callers keep their per-status-code handling.
 */
export async function fetchWithAuth(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: FetchWithAuthOptions = {}
): Promise<Response> {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    throw new Error("No authentication token available");
  }

  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(input, { ...init, headers });

  if (res.status === 401 && !options.suppressAuthRedirect) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen -- bitte erneut anmelden.");
  }

  return res;
}
