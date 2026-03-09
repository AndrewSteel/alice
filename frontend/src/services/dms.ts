import { clearToken, getToken } from "./auth";

const DMS_FOLDERS_ENDPOINT = "/api/webhook/dms/folders";

// ---------- Types ----------

export interface DmsFolder {
  id: number;
  path: string;
  suggested_type: string | null;
  description: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateFolderInput {
  path: string;
  suggested_type?: string | null;
  description?: string | null;
}

export interface UpdateFolderInput {
  path?: string;
  suggested_type?: string | null;
  description?: string | null;
  enabled?: boolean;
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
 * Fetches all DMS watched folders.
 */
export async function getFolders(): Promise<DmsFolder[]> {
  let res: Response;
  try {
    res = await fetch(DMS_FOLDERS_ENDPOINT, {
      method: "GET",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Ordner konnten nicht geladen werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Ordner.`);
  }

  return res.json();
}

/**
 * Creates a new DMS watched folder.
 */
export async function createFolder(data: CreateFolderInput): Promise<DmsFolder> {
  let res: Response;
  try {
    res = await fetch(DMS_FOLDERS_ENDPOINT, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(data),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Ordner konnte nicht erstellt werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 409) {
    throw new Error("Dieser Pfad existiert bereits.");
  }

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || "Ungueltige Eingabe.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Erstellen des Ordners.`);
  }

  return res.json();
}

/**
 * Updates an existing DMS watched folder (partial update).
 */
export async function updateFolder(
  id: number,
  data: UpdateFolderInput
): Promise<DmsFolder> {
  let res: Response;
  try {
    res = await fetch(DMS_FOLDERS_ENDPOINT, {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify({ id, ...data }),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Ordner konnte nicht aktualisiert werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 404) {
    throw new Error("Ordner nicht gefunden.");
  }

  if (res.status === 409) {
    throw new Error("Dieser Pfad existiert bereits.");
  }

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || "Ungueltige Eingabe.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Aktualisieren des Ordners.`);
  }

  return res.json();
}

/**
 * Deletes a DMS watched folder permanently.
 */
export async function deleteFolder(id: number): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${DMS_FOLDERS_ENDPOINT}?id=${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Ordner konnte nicht geloescht werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }

  if (res.status === 404) {
    throw new Error("Ordner nicht gefunden.");
  }

  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || "Ungueltige Eingabe.");
  }

  if (!res.ok && res.status !== 204) {
    throw new Error(`Serverfehler (${res.status}) beim Loeschen des Ordners.`);
  }
}
