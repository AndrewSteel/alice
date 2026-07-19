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
import type { DmsFolder, UpdateFolderInput } from "@/services/dms";

interface EditFolderDialogProps {
  folder: DmsFolder;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (id: number, data: UpdateFolderInput) => Promise<void>;
}

const AUTO_VALUE = "__auto__";

export function EditFolderDialog({
  folder,
  open,
  onOpenChange,
  onSubmit,
}: EditFolderDialogProps) {
  const [path, setPath] = useState(folder.path);
  const [suggestedType, setSuggestedType] = useState<string>(
    folder.suggested_type ?? AUTO_VALUE
  );
  const [description, setDescription] = useState(folder.description ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

    const updates: UpdateFolderInput = {};
    if (trimmedPath !== folder.path) updates.path = trimmedPath;

    const newType = suggestedType === AUTO_VALUE ? null : suggestedType;
    if (newType !== folder.suggested_type) updates.suggested_type = newType;

    const newDesc = description.trim() || null;
    if (newDesc !== folder.description) updates.description = newDesc;

    // Nothing changed
    if (Object.keys(updates).length === 0) {
      onOpenChange(false);
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit(folder.id, updates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Aktualisieren.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border text-foreground sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Ordner bearbeiten</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            Aendere die Einstellungen fuer diesen Ordner.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-path" className="text-foreground">
              Pfad <span className="text-red-400">*</span>
            </Label>
            <Input
              id="edit-path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="bg-background border-border text-foreground font-mono text-sm"
              maxLength={500}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-type" className="text-foreground">
              Dokumenttyp-Hint
            </Label>
            <Select value={suggestedType} onValueChange={setSuggestedType}>
              <SelectTrigger
                id="edit-type"
                className="bg-background border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem value={AUTO_VALUE} className="text-foreground focus:bg-accent focus:text-foreground">
                  Automatisch (LLM)
                </SelectItem>
                {SUGGESTED_TYPES.map((t) => (
                  <SelectItem key={t} value={t} className="text-foreground focus:bg-accent focus:text-foreground">
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-desc" className="text-foreground">
              Beschreibung
            </Label>
            <Input
              id="edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="z.B. Rechnungen 2026"
              className="bg-background border-border text-foreground placeholder:text-muted-foreground"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
              className="text-muted-foreground hover:text-foreground"
            >
              Abbrechen
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {submitting ? "Wird gespeichert..." : "Speichern"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
