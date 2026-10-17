import { fetchWithAuth } from "./fetchWithAuth";
import { STREAM_API_URL } from "./api";

// PROJ-85 — Timer-Agent. Timers are created / changed / deleted through the
// chat (voice or WebApp). The alarm reads the role-scoped list and
// acknowledges an alarm when its toast is closed; the per-role config is
// admin-only.

// ---------- Types ----------

export interface ActiveTimer {
  id: string;
  name: string;
  // "expired": ran out within the catch-up window and nobody actively
  // acknowledged it yet (still ringing, or only ended by the max-time timeout).
  status: "running" | "paused" | "expired";
  expires_at: string; // ISO-8601, absolute
  remaining_seconds: number;
}

export interface ActiveTimersResponse {
  role: string;
  timers: ActiveTimer[];
}

export type TimerRole = "admin" | "user" | "guest" | "child";

export interface TimerRoleConfig {
  role: TimerRole;
  can_use_timers: boolean;
  timer_max_active: number;
  timer_max_duration_seconds: number;
}

export interface TimerConfig {
  default_role: TimerRole;
  roles: TimerRoleConfig[];
}

// ---------- API ----------

function base(): string {
  if (!STREAM_API_URL) {
    throw new Error("Streaming-Endpunkt nicht konfiguriert.");
  }
  // nginx only proxies `${STREAM_API_URL}/stream/*` (and /admin, /auth) to
  // alice-chat-stream — the timer routes live under /stream/ there.
  return `${STREAM_API_URL}/stream`;
}

/** Active timers in the caller's role scope (for the WebApp alarm). */
export async function getActiveTimers(): Promise<ActiveTimersResponse> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${base()}/timers`, { method: "GET" });
  } catch {
    throw new Error("Netzwerkfehler -- Timer konnten nicht geladen werden.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Timer.`);
  }
  return res.json();
}

/**
 * The user closed an expiry toast: acknowledge the alarm server-side (role
 * scope, idempotent). Stops the melody on all Voice PE unless another alarm
 * still rings.
 */
export async function acknowledgeTimers(ids: string[]): Promise<void> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${base()}/timers/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Timer-Alarm nicht quittiert.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Quittieren des Timers.`);
  }
}

/** Per-role timer config + the default role (admin only). */
export async function getTimerConfig(): Promise<TimerConfig> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${base()}/timers/config`, { method: "GET" });
  } catch {
    throw new Error("Netzwerkfehler -- Timer-Einstellungen nicht ladbar.");
  }
  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Einstellungen.`);
  }
  return res.json();
}

/** Update the default role and/or one or more role configs (admin only). */
export async function updateTimerConfig(input: {
  default_role?: TimerRole;
  roles?: TimerRoleConfig[];
}): Promise<TimerConfig> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${base()}/timers/config`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Einstellungen nicht gespeichert.");
  }
  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }
  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Ungueltige Eingabe.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Speichern.`);
  }
  return res.json();
}
