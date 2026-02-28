"use client";

import { createContext, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { decodeJwt } from "jose";
import {
  AuthUser,
  clearToken,
  getToken,
  logout as logoutService,
  setToken,
  validate,
} from "@/services/auth";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = getToken();

    if (!token) {
      setIsLoading(false);
      router.replace("/login");
      return;
    }

    // Lokale Ablaufzeit-Prüfung ohne Netzwerk
    try {
      const payload = decodeJwt(token);
      const exp = payload.exp as number;
      if (exp && Date.now() / 1000 > exp) {
        clearToken();
        setIsLoading(false);
        router.replace("/login");
        return;
      }
    } catch {
      clearToken();
      setIsLoading(false);
      router.replace("/login");
      return;
    }

    // Backend-Validierung (is_active Check)
    validate(token)
      .then((u) => setUser(u))
      .catch(() => {
        clearToken();
        router.replace("/login");
      })
      .finally(() => setIsLoading(false));
  }, [router]);

  const login = useCallback((token: string, u: AuthUser) => {
    setToken(token);
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    const token = getToken();
    if (token) logoutService(token);
    setUser(null);
    router.replace("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
