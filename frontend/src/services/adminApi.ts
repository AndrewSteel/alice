import { clearToken, getToken } from "./auth";

const ADMIN_BASE = "/api/auth/admin";

// ---------- Types ----------

export interface AdminUser {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface CreateUserInput {
  username: string;
  email: string;
  role: string;
  // Profile facts
  name?: string;
  rolle?: string;
  // Profile preferences
  anrede?: string;
  sprache?: string;
  detailgrad?: string;
}

// ---------- Helpers ----------

function authHeaders(): HeadersInit {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    throw new Error("No authentication token available");
  }
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

function handleAuthError(res: Response): void {
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen -- bitte erneut anmelden.");
  }
}

// ---------- API Functions ----------

/**
 * Fetches all users (admin only).
 */
export async function getUsers(): Promise<AdminUser[]> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}/users`, {
      method: "GET",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Nutzer konnten nicht geladen werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Nutzer.`);
  }

  const data = await res.json();
  return Array.isArray(data) ? data : data.users ?? [];
}

/**
 * Creates a new user with OTP generation and email sending.
 */
export async function createUser(input: CreateUserInput): Promise<AdminUser> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}/users`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Nutzer konnte nicht angelegt werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Benutzername oder E-Mail bereits vergeben.");
  }

  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || "Ungueltige Eingabe.");
  }

  if (res.status === 500) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      body.detail ||
        "E-Mail-Versand fehlgeschlagen -- Nutzer wurde nicht angelegt. SMTP pruefen."
    );
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Anlegen des Nutzers.`);
  }

  return res.json();
}

/**
 * Resets OTP for a user and sends new OTP via email.
 */
export async function resetOtp(userId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}/users/${userId}/reset-otp`, {
      method: "POST",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- OTP konnte nicht zurueckgesetzt werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 404) {
    throw new Error("Nutzer nicht gefunden.");
  }

  if (res.status === 500) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      body.detail || "E-Mail-Versand fehlgeschlagen -- SMTP pruefen."
    );
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) beim Zuruecksetzen des OTP.`
    );
  }
}

/**
 * Activates or deactivates a user.
 */
export async function updateUserStatus(
  userId: string,
  isActive: boolean
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}/users/${userId}/status`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({ is_active: isActive }),
    });
  } catch {
    throw new Error(
      "Netzwerkfehler -- Status konnte nicht geaendert werden."
    );
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 404) {
    throw new Error("Nutzer nicht gefunden.");
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) beim Aendern des Status.`
    );
  }
}

/**
 * Permanently deletes a user.
 */
export async function deleteUser(userId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}/users/${userId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Nutzer konnte nicht geloescht werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 404) {
    throw new Error("Nutzer nicht gefunden.");
  }

  if (!res.ok && res.status !== 204) {
    throw new Error(
      `Serverfehler (${res.status}) beim Loeschen des Nutzers.`
    );
  }
}

/**
 * Changes the current user's password (used for forced password change after OTP login).
 */
export async function changePassword(
  newPassword: string
): Promise<void> {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    throw new Error("No authentication token available");
  }

  let res: Response;
  try {
    res = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ new_password: newPassword }),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Passwort konnte nicht geaendert werden.");
  }

  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen -- bitte erneut anmelden.");
  }

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      body.detail || "Das neue Passwort erfuellt nicht die Anforderungen."
    );
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) beim Aendern des Passworts.`
    );
  }
}
