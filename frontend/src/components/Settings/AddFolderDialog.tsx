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
import { useTranslation } from "react-i18next";
import { SUGGESTED_TYPES } from "./dms-constants";
import type { CreateFolderInput } from "@/services/dms";

interface AddFolderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: CreateFolderInput) => Promise<void>;
}

const AUTO_VALUE = "__auto__";

export function AddFolderDialog({
  open,
  onOpenChange,
  onSubmit,
}: AddFolderDialogProps) {
  const { t } = useTranslation();
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
      setError(t("settings.dms.dialog.pathRequired"));
      return;
    }
    if (trimmedPath.length > 500) {
      setError(t("settings.dms.dialog.pathTooLong"));
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
      setError(err instanceof Error ? err.message : t("settings.dms.createError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-card border-border text-foreground sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("settings.dms.dialog.addTitle")}</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {t("settings.dms.dialog.addDesc")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="add-path" className="text-foreground">
              {t("settings.dms.dialog.pathLabel")} <span className="text-red-400">*</span>
            </Label>
            <Input
              id="add-path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder={t("settings.dms.dialog.pathPlaceholder")}
              className="bg-background border-border text-foreground placeholder:text-muted-foreground font-mono text-sm"
              maxLength={500}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-type" className="text-foreground">
              {t("settings.dms.dialog.typeLabel")}
            </Label>
            <Select value={suggestedType} onValueChange={setSuggestedType}>
              <SelectTrigger
                id="add-type"
                className="bg-background border-border text-foreground"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-card border-border">
                <SelectItem
                  value={AUTO_VALUE}
                  className="text-foreground focus:bg-accent focus:text-foreground"
                >
                  {t("settings.dms.dialog.autoLlm")}
                </SelectItem>
                {SUGGESTED_TYPES.map((t) => (
                  <SelectItem
                    key={t}
                    value={t}
                    className="text-foreground focus:bg-accent focus:text-foreground"
                  >
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-desc" className="text-foreground">
              {t("settings.dms.dialog.descLabel")}
            </Label>
            <Input
              id="add-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("settings.dms.dialog.descPlaceholder")}
              className="bg-background border-border text-foreground placeholder:text-muted-foreground"
            />
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
              className="text-muted-foreground hover:text-foreground"
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {submitting ? t("settings.dms.dialog.creating") : t("settings.dms.dialog.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
