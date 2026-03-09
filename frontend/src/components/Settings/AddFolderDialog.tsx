"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SUGGESTED_TYPES } from "./dms-constants";
import type { CreateFolderInput } from "@/services/dms";

interface AddFolderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: CreateFolderInput) => Promise<void>;
}

const AUTO_VALUE = "__auto__";

export function AddFolderDialog({ open, onOpenChange, onSubmit }: AddFolderDialogProps) {
  const [path, setPath] = useState("");
  const [suggestedType, setSuggestedType] = useState<string>(AUTO_VALUE);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function resetForm() {
    setPath("");
    setSuggestedType(AUTO_VALUE);
    setDescription("");
    setError(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next) resetForm();
    onOpenChange(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedPath = path.trim();
    if (!trimmedPath) {
      setError("Pfad ist erforderlich.");
      return;
    }
    if (trimmedPath.length > 500) {
      setError("Pfad darf maximal 500 Zeichen lang sein.");
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({
        path: trimmedPath,
        suggested_type: suggestedType === AUTO_VALUE ? null : suggestedType,
        description: description.trim() || null,
      });
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Erstellen.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-gray-800 border-gray-700 text-gray-100 sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Ordner hinzufuegen</DialogTitle>
          <DialogDescription className="text-gray-400">
            Fuege einen NAS-Pfad zur DMS-Ueberwachung hinzu.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="add-path" className="text-gray-300">
              Pfad <span className="text-red-400">*</span>
            </Label>
            <Input
              id="add-path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/mnt/nas/dokumente/rechnungen"
              className="bg-gray-900 border-gray-600 text-gray-100 placeholder:text-gray-500 font-mono text-sm"
              maxLength={500}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-type" className="text-gray-300">
              Dokumenttyp-Hint
            </Label>
            <Select value={suggestedType} onValueChange={setSuggestedType}>
              <SelectTrigger
                id="add-type"
                className="bg-gray-900 border-gray-600 text-gray-100"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-gray-800 border-gray-700">
                <SelectItem value={AUTO_VALUE} className="text-gray-300 focus:bg-gray-700 focus:text-gray-100">
                  Automatisch (LLM)
                </SelectItem>
                {SUGGESTED_TYPES.map((t) => (
                  <SelectItem key={t} value={t} className="text-gray-300 focus:bg-gray-700 focus:text-gray-100">
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-desc" className="text-gray-300">
              Beschreibung
            </Label>
            <Input
              id="add-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="z.B. Rechnungen 2026"
              className="bg-gray-900 border-gray-600 text-gray-100 placeholder:text-gray-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
              className="text-gray-400 hover:text-gray-100"
            >
              Abbrechen
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {submitting ? "Wird erstellt..." : "Hinzufuegen"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
