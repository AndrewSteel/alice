"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { CreateUserInput } from "@/services/adminApi";

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (data: CreateUserInput) => Promise<void>;
}

const ROLES = ["admin", "user", "guest", "child"] as const;
const ANREDE_OPTIONS = ["du", "sie"] as const;
const SPRACHE_OPTIONS = ["deutsch", "englisch"] as const;
const DETAILGRAD_OPTIONS = ["technisch", "normal", "einfach", "kindlich"] as const;

export function CreateUserDialog({
  open,
  onOpenChange,
  onConfirm,
}: CreateUserDialogProps) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("user");
  const [name, setName] = useState("");
  const [rolle, setRolle] = useState("");
  const [anrede, setAnrede] = useState<string>("du");
  const [sprache, setSprache] = useState<string>("deutsch");
  const [detailgrad, setDetailgrad] = useState<string>("normal");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function resetForm() {
    setUsername("");
    setEmail("");
    setRole("user");
    setName("");
    setRolle("");
    setAnrede("du");
    setSprache("deutsch");
    setDetailgrad("normal");
    setError(null);
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      resetForm();
    }
    onOpenChange(nextOpen);
  }

  const isEmailValid =
    email.trim() === "" || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const canSubmit =
    !isSubmitting &&
    username.trim().length > 0 &&
    email.trim().length > 0 &&
    isEmailValid &&
    role.length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setError(null);
    setIsSubmitting(true);

    try {
      const input: CreateUserInput = {
        username: username.trim(),
        email: email.trim(),
        role,
      };

      if (name.trim()) input.name = name.trim();
      if (rolle.trim()) input.rolle = rolle.trim();
      if (anrede) input.anrede = anrede;
      if (sprache) input.sprache = sprache;
      if (detailgrad) input.detailgrad = detailgrad;

      await onConfirm(input);
      resetForm();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unbekannter Fehler.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Neuer Nutzer</DialogTitle>
          <DialogDescription className="text-gray-400">
            Ein Einmal-Passwort wird generiert und per E-Mail an den neuen
            Nutzer gesendet.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* --- Basis-Daten --- */}
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="create-username" className="text-gray-300">
                Benutzername <span className="text-red-400">*</span>
              </Label>
              <Input
                id="create-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isSubmitting}
                className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500"
                placeholder="z.B. maria"
                autoComplete="off"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="create-email" className="text-gray-300">
                E-Mail-Adresse <span className="text-red-400">*</span>
              </Label>
              <Input
                id="create-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isSubmitting}
                className={`bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500 ${
                  email.trim() && !isEmailValid ? "border-red-500" : ""
                }`}
                placeholder="nutzer@example.com"
                autoComplete="off"
                required
              />
              {email.trim() && !isEmailValid && (
                <p className="text-xs text-red-400">
                  Bitte eine gueltige E-Mail-Adresse eingeben.
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="create-role" className="text-gray-300">
                Systemrolle <span className="text-red-400">*</span>
              </Label>
              <Select value={role} onValueChange={setRole} disabled={isSubmitting}>
                <SelectTrigger
                  id="create-role"
                  className="bg-gray-700 border-gray-600 text-gray-100"
                >
                  <SelectValue placeholder="Rolle waehlen" />
                </SelectTrigger>
                <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                  {ROLES.map((r) => (
                    <SelectItem
                      key={r}
                      value={r}
                      className="focus:bg-gray-700 focus:text-gray-100"
                    >
                      {r}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <Separator className="bg-gray-700" />

          {/* --- Profil-Daten (optional) --- */}
          <div className="space-y-3">
            <p className="text-sm font-medium text-gray-300">
              Profil (optional)
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="create-name" className="text-gray-400 text-sm">
                  Name
                </Label>
                <Input
                  id="create-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={isSubmitting}
                  className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500"
                  placeholder="z.B. Maria"
                  autoComplete="off"
                />
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="create-rolle"
                  className="text-gray-400 text-sm"
                >
                  Rolle (Beschreibung)
                </Label>
                <Input
                  id="create-rolle"
                  value={rolle}
                  onChange={(e) => setRolle(e.target.value)}
                  disabled={isSubmitting}
                  className="bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 focus:border-blue-500"
                  placeholder="z.B. Mutter"
                  autoComplete="off"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label
                  htmlFor="create-anrede"
                  className="text-gray-400 text-sm"
                >
                  Anrede
                </Label>
                <Select
                  value={anrede}
                  onValueChange={setAnrede}
                  disabled={isSubmitting}
                >
                  <SelectTrigger
                    id="create-anrede"
                    className="bg-gray-700 border-gray-600 text-gray-100"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                    {ANREDE_OPTIONS.map((a) => (
                      <SelectItem
                        key={a}
                        value={a}
                        className="focus:bg-gray-700 focus:text-gray-100"
                      >
                        {a}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="create-sprache"
                  className="text-gray-400 text-sm"
                >
                  Sprache
                </Label>
                <Select
                  value={sprache}
                  onValueChange={setSprache}
                  disabled={isSubmitting}
                >
                  <SelectTrigger
                    id="create-sprache"
                    className="bg-gray-700 border-gray-600 text-gray-100"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                    {SPRACHE_OPTIONS.map((s) => (
                      <SelectItem
                        key={s}
                        value={s}
                        className="focus:bg-gray-700 focus:text-gray-100"
                      >
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="create-detailgrad"
                  className="text-gray-400 text-sm"
                >
                  Detailgrad
                </Label>
                <Select
                  value={detailgrad}
                  onValueChange={setDetailgrad}
                  disabled={isSubmitting}
                >
                  <SelectTrigger
                    id="create-detailgrad"
                    className="bg-gray-700 border-gray-600 text-gray-100"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                    {DETAILGRAD_OPTIONS.map((d) => (
                      <SelectItem
                        key={d}
                        value={d}
                        className="focus:bg-gray-700 focus:text-gray-100"
                      >
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleOpenChange(false)}
              disabled={isSubmitting}
              className="text-gray-300 hover:bg-gray-700 hover:text-gray-100"
            >
              Abbrechen
            </Button>
            <Button
              type="submit"
              disabled={!canSubmit}
              className="bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
            >
              {isSubmitting ? "Wird angelegt..." : "Anlegen"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
