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
import { Folder } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SUGGESTED_TYPES } from "./dms-constants";
import { FolderPathPicker } from "./FolderPathPicker";
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
  const { t } = useTranslation();
  const [path, setPath] = useState(folder.path);
  const [suggestedType, setSuggestedType] = useState<string>(
    folder.suggested_type ?? AUTO_VALUE
  );
  const [description, setDescription] = useState(folder.description ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

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
      setError(err instanceof Error ? err.message : t("settings.dms.updateError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border text-foreground sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("settings.dms.dialog.editTitle")}</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {t("settings.dms.dialog.editDesc")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="min-w-0 space-y-4">
          <div className="min-w-0 space-y-2">
            <Label className="text-foreground">
              {t("settings.dms.dialog.pathLabel")} <span className="text-red-400">*</span>
            </Label>
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              title={path || undefined}
              aria-label={t("settings.dms.dialog.choosePath")}
              className="flex w-full min-w-0 items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-2 text-left font-mono text-sm text-foreground hover:bg-accent"
            >
              <span className="min-w-0 flex-1 truncate">
                {path || (
                  <span className="font-sans text-muted-foreground">
                    {t("settings.dms.dialog.pathPlaceholder")}
                  </span>
                )}
              </span>
              <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-type" className="text-foreground">
              {t("settings.dms.dialog.typeLabel")}
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
                  {t("settings.dms.dialog.autoLlm")}
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
              {t("settings.dms.dialog.descLabel")}
            </Label>
            <Input
              id="edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("settings.dms.dialog.descPlaceholder")}
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
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {submitting ? t("common.saving") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>

      <FolderPathPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        startPath={folder.path}
        excludeFolderId={folder.id}
        onSelect={setPath}
      />
    </Dialog>
  );
}
