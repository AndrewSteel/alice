"use client";

import { useState } from "react";
import { Eye, EyeOff, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login as loginService } from "@/services/auth";
import { useAuth } from "@/hooks/useAuth";

export function LoginForm() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const isDisabled = isLoading || !username.trim() || !password.trim();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      const { token, user } = await loginService(username.trim(), password);
      login(token, user);
      window.location.href = "/";
    } catch (err) {
      if (err instanceof Error && err.message === "NETWORK_ERROR") {
        setError("Verbindungsfehler — bitte erneut versuchen");
      } else {
        setError("Ungültige Anmeldedaten");
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center w-full">
      {/* Logo */}
      <div className="flex items-center gap-2 mb-8">
        <Bot className="h-8 w-8 text-blue-500" aria-hidden />
        <span className="text-2xl font-bold text-gray-100">Alice</span>
      </div>

      <form
        onSubmit={handleSubmit}
        className="w-full space-y-4"
        aria-label="Anmeldung"
        noValidate
      >
        <div className="space-y-1.5">
          <Label htmlFor="username" className="text-gray-300">
            Benutzername
          </Label>
          <Input
            id="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={isLoading}
            className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500"
            placeholder="Benutzername"
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-gray-300">
            Passwort
          </Label>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500 pr-10"
              placeholder="Passwort"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 transition-colors"
              aria-label={showPassword ? "Passwort verbergen" : "Passwort anzeigen"}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}

        <Button
          type="submit"
          disabled={isDisabled}
          className="w-full bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
        >
          {isLoading ? "Wird angemeldet…" : "Anmelden"}
        </Button>
      </form>
    </div>
  );
}
