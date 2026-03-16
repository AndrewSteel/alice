import { clearToken, getToken } from "./auth";

const AUTH_BASE = "/api/auth";

// ---------- Types ----------

export interface ProfileData {
  username: string;
  email: string | null;
  facts: {
    name: string | null;
    rolle: string | null;
    interessen: string[];
  };
  preferences: {
    anrede: "du" | "sie" | null;
    sprache: "deutsch" | "englisch" | null;
    detailgrad: string | null;
  };
}

export interface ProfileUpdateInput {
  name: string | null;
  interessen: string[];
  anrede: "du" | "sie";
  sprache: "deutsch" | "englisch";
}

export interface EmailUpdateInput {
  email: string;
}

export interface VoluntaryPasswordChangeInput {
  current_password: string;
  new_password: string;
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
 * Fetches the current user's profile data.
 */
export async function getProfile(): Promise<ProfileData> {
  let res: Response;
  try {
    res = await fetch(`${AUTH_BASE}/profile`, {
      method: "GET",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Profil konnte nicht geladen werden.");
  }

  handleAuthError(res);

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden des Profils.`);
  }

  return res.json();
}

/**
 * Updates profile facts and preferences (name, interessen, anrede, sprache).
 */
export async function updateProfile(input: ProfileUpdateInput): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${AUTH_BASE}/profile`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Fehler beim Speichern. Bitte erneut versuchen.");
  }

  handleAuthError(res);

  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Ungueltige Eingabe.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Speichern des Profils.`);
  }
}

/**
 * Updates the user's email address (with format + MX validation on the backend).
 */
export async function updateEmail(input: EmailUpdateInput): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${AUTH_BASE}/email`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Fehler beim Speichern. Bitte erneut versuchen.");
  }

  handleAuthError(res);

  if (res.status === 409) {
    throw new Error("E-Mail-Adresse wird bereits verwendet");
  }

  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail || "";
    if (detail.toLowerCase().includes("mx") || detail.toLowerCase().includes("domain")) {
      throw new Error("E-Mail-Domain akzeptiert keine E-Mails");
    }
    throw new Error("Ungueltige E-Mail-Adresse");
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) beim Aendern der E-Mail-Adresse.`
    );
  }
}

/**
 * Voluntary password change (requires current password confirmation).
 */
export async function changePasswordVoluntary(
  input: VoluntaryPasswordChangeInput
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${AUTH_BASE}/change-password-voluntary`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Fehler beim Speichern. Bitte erneut versuchen.");
  }

  // For this endpoint, 401 can mean either "wrong current password" or "expired token".
  // Parse the body first to differentiate before potentially logging the user out.
  if (res.status === 401) {
    const body = await res.json().catch(() => ({}));
    const detail = (body.detail || "").toLowerCase();
    if (detail.includes("passwort") || detail.includes("password") || detail.includes("incorrect") || detail.includes("falsch")) {
      throw new Error("Aktuelles Passwort ist falsch");
    }
    // Not a wrong-password 401 — treat as expired session
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen -- bitte erneut anmelden.");
  }

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail || "";
    if (detail.toLowerCase().includes("unterscheiden") || detail.toLowerCase().includes("same")) {
      throw new Error("Neues Passwort muss sich vom aktuellen unterscheiden");
    }
    if (detail.toLowerCase().includes("zeichen") || detail.toLowerCase().includes("character") || detail.toLowerCase().includes("min")) {
      throw new Error("Passwort muss mindestens 8 Zeichen haben");
    }
    throw new Error(detail || "Ungueltige Eingabe.");
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) beim Aendern des Passworts.`
    );
  }
}
