import { fetchWithAuth } from "./fetchWithAuth";

// PROJ-87 — Kalender-Agent. Settings tab endpoints (alice-calendar) plus the
// PROJ-86 consent/disconnect endpoints (alice-google-connect). Calendars are
// read live from Google on every load; only the selection is stored.

const CALENDAR_BASE = "/api/calendar";
const GOOGLE_BASE = "/api/google";

// ---------- Types ----------

export interface GoogleCalendar {
  id: string;
  name: string;
  color: string | null;
  read_only: boolean;
  primary: boolean;
  is_active: boolean;
  is_default: boolean;
}

export interface CalendarAccount {
  connection_id: string;
  google_account: string;
  status: "active" | "error";
  has_calendar_scope: boolean;
  /** Connection also carries other Google scopes (tasks/contacts) — disconnect warning. */
  has_other_scopes: boolean;
  calendars: GoogleCalendar[] | null;
  calendars_error: "reauth_required" | "unavailable" | null;
}

export interface CalendarAccountsResponse {
  required_scopes: string[];
  accounts: CalendarAccount[];
}

export interface CalendarSelection {
  connection_id: string;
  calendar_id: string;
  is_active: boolean;
  is_default: boolean;
}

export type CalendarRole = "admin" | "user" | "guest" | "child";

export interface CalendarRoleFlag {
  role: CalendarRole;
  can_use_calendar: boolean;
}

/** Error carrying the HTTP status so the UI can pick a translated message. */
export class CalendarApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function detail(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

// ---------- Settings tab ----------

export async function getCalendarAccounts(): Promise<CalendarAccountsResponse> {
  const res = await fetchWithAuth(`${CALENDAR_BASE}/accounts`, { method: "GET" });
  if (!res.ok) throw new CalendarApiError(res.status, await detail(res));
  return res.json();
}

export async function updateCalendarSelection(input: {
  connection_id: string;
  calendar_id: string;
  is_active?: boolean;
  is_default?: boolean;
}): Promise<CalendarSelection[]> {
  const res = await fetchWithAuth(`${CALENDAR_BASE}/selection`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new CalendarApiError(res.status, await detail(res));
  const body = await res.json();
  return body.selections as CalendarSelection[];
}

/** Starts the Google consent flow; the browser returns to /settings/kalender. */
export async function startCalendarConsent(scopes: string[]): Promise<string> {
  const res = await fetchWithAuth(`${GOOGLE_BASE}/connect/start`, {
    method: "POST",
    body: JSON.stringify({ scopes, return_to: "kalender" }),
  });
  if (!res.ok) throw new CalendarApiError(res.status, await detail(res));
  const body = await res.json();
  return body.auth_url as string;
}

/** Disconnects the whole Google account (all scopes, revoke at Google). */
export async function disconnectGoogleAccount(connectionId: string): Promise<void> {
  const res = await fetchWithAuth(`${GOOGLE_BASE}/connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) throw new CalendarApiError(res.status, await detail(res));
}

// ---------- Admin: role permission ----------

export async function getCalendarRoles(): Promise<CalendarRoleFlag[]> {
  const res = await fetchWithAuth(`${CALENDAR_BASE}/admin/roles`, { method: "GET" });
  if (!res.ok) throw new CalendarApiError(res.status, await detail(res));
  return (await res.json()).roles;
}

export async function updateCalendarRoles(roles: CalendarRoleFlag[]): Promise<CalendarRoleFlag[]> {
  const res = await fetchWithAuth(`${CALENDAR_BASE}/admin/roles`, {
    method: "PUT",
    body: JSON.stringify({ roles }),
  });
  if (!res.ok) throw new CalendarApiError(res.status, await detail(res));
  return (await res.json()).roles;
}
