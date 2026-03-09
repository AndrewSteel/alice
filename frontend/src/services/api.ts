import { clearToken, getToken } from "./auth";

const CHAT_ENDPOINT = "/api/webhook/v1/chat/completions";
const SESSIONS_ENDPOINT = "/api/webhook/alice/sessions";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SessionResponse {
  session_id: string;
  title: string | null;
  started_at: string;
  last_activity: string;
}

export interface MessageResponse {
  role: string;
  content: string;
  timestamp: string;
}

// ---------- Helper ----------

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

// ---------- Session API ----------

/**
 * Fetches all sessions for the authenticated user.
 */
export async function fetchSessions(): Promise<SessionResponse[]> {
  let res: Response;
  try {
    res = await fetch(SESSIONS_ENDPOINT, {
      method: "GET",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Sessions konnten nicht geladen werden.");
  }

  handleAuthError(res);

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Sessions.`);
  }

  const data = await res.json();

  // The API returns { sessions: [...] } — extract the array
  if (Array.isArray(data)) {
    return data;
  }
  if (data && Array.isArray(data.sessions)) {
    return data.sessions;
  }

  return [];
}

/**
 * Fetches all messages for a given session.
 */
export async function fetchSessionMessages(
  sessionId: string
): Promise<MessageResponse[]> {
  let res: Response;
  try {
    res = await fetch(`${SESSIONS_ENDPOINT}/messages?session_id=${encodeURIComponent(sessionId)}`, {
      method: "GET",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Nachrichten konnten nicht geladen werden.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Kein Zugriff auf diese Session.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Nachrichten.`);
  }

  const data = await res.json();

  // The API may return { messages: [...] } or a plain array
  if (Array.isArray(data)) {
    return data;
  }
  if (data && Array.isArray(data.messages)) {
    return data.messages;
  }

  return [];
}

/**
 * Renames a session on the backend.
 */
export async function renameSessionApi(
  sessionId: string,
  title: string
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(SESSIONS_ENDPOINT, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({ session_id: sessionId, title }),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Umbenennen fehlgeschlagen.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Kein Zugriff auf diese Session.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Umbenennen.`);
  }
}

/**
 * Deletes a session on the backend.
 */
export async function deleteSessionApi(sessionId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${SESSIONS_ENDPOINT}?session_id=${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Loeschen fehlgeschlagen.");
  }

  handleAuthError(res);

  if (res.status === 403) {
    throw new Error("Kein Zugriff auf diese Session.");
  }

  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Loeschen.`);
  }
}

export interface ChatCompletionResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: {
    index: number;
    message: { role: string; content: string };
    finish_reason: string;
  }[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/**
 * Sends a chat message to the Alice backend.
 * Automatically attaches the JWT Bearer token.
 * On 401, clears the token and redirects to /login.
 */
export async function sendMessage(
  messages: ChatMessage[],
  sessionId: string
): Promise<string> {
  const token = getToken();

  if (!token) {
    window.location.href = "/login";
    throw new Error("No authentication token available");
  }

  let res: Response;
  try {
    res = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        messages,
        session_id: sessionId,
      }),
    });
  } catch {
    throw new Error(
      "Netzwerkfehler -- bitte pruefe deine Verbindung und versuche es erneut."
    );
  }

  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session abgelaufen -- bitte erneut anmelden.");
  }

  if (res.status === 429) {
    throw new Error("Zu viele Anfragen -- bitte kurz warten.");
  }

  if (!res.ok) {
    throw new Error(
      `Serverfehler (${res.status}) -- bitte versuche es erneut.`
    );
  }

  let data: ChatCompletionResponse;
  try {
    data = await res.json();
  } catch {
    throw new Error("Ungueltige Antwort vom Server -- bitte versuche es erneut.");
  }

  const assistantMessage = data.choices?.[0]?.message?.content;
  if (!assistantMessage) {
    throw new Error("Keine Antwort von Alice erhalten.");
  }

  return assistantMessage;
}
