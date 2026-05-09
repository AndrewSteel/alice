import { clearToken, getToken } from "./auth";

const CHAT_ENDPOINT = "/api/webhook/v1/chat/completions";
const SESSIONS_ENDPOINT = "/api/webhook/alice/sessions";

/**
 * Streaming endpoint base URL. When undefined, the chat falls back to
 * the legacy non-streaming `sendMessage()` path (PROJ-31 backwards compat).
 */
export const STREAM_API_URL: string | undefined =
  process.env.NEXT_PUBLIC_STREAM_API_URL;

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

// ---------- Streaming Chat (PROJ-31) ----------

export interface StreamCallbacks {
  onToken: (text: string) => void;
  onToolStart: (tool: string, status?: string) => void;
  onToolEnd: (tool: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

export interface StreamHandle {
  abort: () => void;
}

interface SseEvent {
  type: "token" | "tool_start" | "tool_end" | "done" | "error";
  content?: string;
  tool?: string;
  status?: string;
  message?: string;
}

/**
 * Opens an SSE stream to the alice-chat-stream backend.
 *
 * Uses fetch() + ReadableStream instead of EventSource because EventSource
 * does not support custom HTTP headers (we need Authorization: Bearer ...).
 *
 * Returns an abort handle that the caller can use to close the stream
 * (e.g. when the user clicks "Stopp").
 */
export function streamChat(
  sessionId: string,
  content: string,
  callbacks: StreamCallbacks
): StreamHandle {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return { abort: () => {} };
  }

  if (!STREAM_API_URL) {
    callbacks.onError(
      "Streaming-Endpunkt nicht konfiguriert (NEXT_PUBLIC_STREAM_API_URL fehlt)."
    );
    return { abort: () => {} };
  }

  const controller = new AbortController();
  let aborted = false;

  const abort = () => {
    if (aborted) return;
    aborted = true;
    controller.abort();
  };

  (async () => {
    let res: Response;
    try {
      res = await fetch(`${STREAM_API_URL}/stream/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ session_id: sessionId, content }),
        signal: controller.signal,
      });
    } catch (err) {
      if (aborted || (err as Error)?.name === "AbortError") return;
      callbacks.onError(
        "Verbindung unterbrochen. Bitte erneut versuchen."
      );
      return;
    }

    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      return;
    }
    if (res.status === 429) {
      callbacks.onError("Zu viele Anfragen -- bitte kurz warten.");
      return;
    }
    if (!res.ok || !res.body) {
      callbacks.onError(
        `Serverfehler (${res.status}) -- bitte versuche es erneut.`
      );
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let done = false;

    try {
      while (!done && !aborted) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE events are separated by a blank line ("\n\n").
        let separatorIdx: number;
        while ((separatorIdx = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, separatorIdx);
          buffer = buffer.slice(separatorIdx + 2);

          // An event can have multiple "data:" lines -- concatenate them.
          const dataLines: string[] = [];
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trimStart());
            }
          }
          if (dataLines.length === 0) continue;
          const payload = dataLines.join("\n");

          if (payload === "[DONE]") {
            done = true;
            break;
          }

          let evt: SseEvent;
          try {
            evt = JSON.parse(payload);
          } catch {
            continue;
          }

          switch (evt.type) {
            case "token":
              if (typeof evt.content === "string") {
                callbacks.onToken(evt.content);
              }
              break;
            case "tool_start":
              if (evt.tool) {
                callbacks.onToolStart(evt.tool, evt.status);
              }
              break;
            case "tool_end":
              if (evt.tool) {
                callbacks.onToolEnd(evt.tool);
              }
              break;
            case "error":
              callbacks.onError(
                evt.message || "Unbekannter Fehler vom Server."
              );
              done = true;
              break;
            case "done":
              done = true;
              break;
          }
        }
      }
    } catch (err) {
      if (!aborted && (err as Error)?.name !== "AbortError") {
        callbacks.onError(
          "Verbindung unterbrochen. Bitte erneut versuchen."
        );
        return;
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // ignore
      }
    }

    if (!aborted) {
      callbacks.onDone();
    }
  })();

  return { abort };
}
