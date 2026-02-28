import { clearToken, getToken } from "./auth";

const CHAT_ENDPOINT = "/api/webhook/v1/chat/completions";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
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
