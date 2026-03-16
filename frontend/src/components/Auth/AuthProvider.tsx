"use client";

import { createContext, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { decodeJwt } from "jose";
import {
  AuthUser,
  ValidateResponse,
  clearToken,
  getToken,
  logout as logoutService,
  setToken,
  validate,
} from "@/services/auth";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  mustChangePassword: boolean;
  login: (token: string, user: AuthUser, mustChangePassword?: boolean) => void;
  logout: () => void;
  clearMustChangePassword: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  useEffect(() => {
    const token = getToken();

    if (!token) {
      setIsLoading(false);
      router.replace("/login");
      return;
    }

    // Lokale Ablaufzeit-Prüfung ohne Netzwerk
    let localUser: AuthUser | null = null;
    try {
      const payload = decodeJwt(token);
      const exp = payload.exp as number;
      if (exp && Date.now() / 1000 > exp) {
        clearToken();
        setIsLoading(false);
        router.replace("/login");
        return;
      }
      // Extract user from JWT for fallback on rate-limit
      localUser = {
        id: payload.sub as string,
        username: payload.username as string,
        role: payload.role as string,
      };
    } catch {
      clearToken();
      setIsLoading(false);
      router.replace("/login");
      return;
    }

    // Backend-Validierung (is_active Check + must_change_password)
    validate(token)
      .then(({ user: u, mustChangePassword: mcp }: ValidateResponse) => {
        setUser(u);
        if (mcp) setMustChangePassword(true);
      })
      .catch((err) => {
        // On 429 (rate-limited): fall back to JWT-decoded user, keep token
        if (err instanceof Error && err.message === "RATE_LIMITED") {
          if (localUser) setUser(localUser);
          return;
        }
        clearToken();
        router.replace("/login");
      })
      .finally(() => setIsLoading(false));
  }, [router]);

  const login = useCallback((token: string, u: AuthUser, mustChange?: boolean) => {
    setToken(token);
    setUser(u);
    if (mustChange) setMustChangePassword(true);
  }, []);

  const clearMustChangePassword = useCallback(() => {
    setMustChangePassword(false);
  }, []);

  const logout = useCallback(() => {
    const token = getToken();
    if (token) logoutService(token);
    setUser(null);
    router.replace("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, isLoading, mustChangePassword, login, logout, clearMustChangePassword }}>
      {children}
    </AuthContext.Provider>
  );
}
