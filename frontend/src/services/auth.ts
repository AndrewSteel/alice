const AUTH_BASE = "/api/webhook/auth";
const TOKEN_KEY = "alice_token";

export interface AuthUser {
  id: string;
  username: string;
  role: string;
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  let res: Response;
  try {
    res = await fetch(`${AUTH_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("NETWORK_ERROR");
  }
  if (!res.ok) {
    throw new Error("Ungültige Anmeldedaten");
  }
  return res.json();
}

export async function validate(token: string): Promise<AuthUser> {
  const res = await fetch(`${AUTH_BASE}/validate`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error("Token ungültig");
  }
  const data = await res.json();
  return data.user;
}

export async function logout(token: string): Promise<void> {
  // fire-and-forget
  fetch(`${AUTH_BASE}/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => {});
  clearToken();
}
