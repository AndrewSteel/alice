"use client";

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AlertCircle, Folder, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { browseFolders, type BrowseEntry } from "@/services/dms";

const MOUNT = "/mnt/nas";

interface FolderPathPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startPath: string;
  excludeFolderId?: number;
  onSelect: (path: string) => void;
}

function conflictBadgeVariant(type: NonNullable<BrowseEntry["conflictType"]>) {
  if (type === "exact") return "destructive" as const;
  if (type === "ancestor") return "secondary" as const;
  return "outline" as const;
}

export function FolderPathPicker({
  open,
  onOpenChange,
  startPath,
  excludeFolderId,
  onSelect,
}: FolderPathPickerProps) {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState(startPath);
  const [currentConflict, setCurrentConflict] = useState<BrowseEntry["conflictType"]>(null);
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCurrentPath(startPath);
  }, [open, startPath]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    browseFolders(currentPath, excludeFolderId)
      .then((res) => {
        if (cancelled) return;
        setEntries(res.entries);
        setCurrentConflict(res.conflictType);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t("settings.dms.picker.errorGeneric"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, currentPath, excludeFolderId]);

  function handleSelect() {
    onSelect(currentPath);
    onOpenChange(false);
  }

  const isRoot = currentPath === MOUNT;
  const relative = isRoot ? "" : currentPath.slice(MOUNT.length + 1);
  const segments = relative ? relative.split("/") : [];
  // Refinement 2026-08-04: only an exact-path match blocks selection.
  // Ancestor/descendant overlap is an accepted trade-off (e.g. a broad
  // collector folder alongside specifically-typed subfolders) — still
  // shown as an informational badge, but no longer disables the button.
  const hasConflict = currentConflict === "exact";

  // depth 0 = /mnt/nas itself, depth n = /mnt/nas plus the first n path segments.
  // Computed directly from the path string so breadcrumb navigation is always
  // correct regardless of how the picker got to the current path (deep initial
  // open in Edit mode, a row click, or a previous breadcrumb jump).
  function pathAtDepth(depth: number) {
    return depth === 0 ? MOUNT : `${MOUNT}/${segments.slice(0, depth).join("/")}`;
  }

  function conflictLabel(type: NonNullable<BrowseEntry["conflictType"]>) {
    if (type === "exact") return t("settings.dms.picker.conflictExact");
    if (type === "ancestor") return t("settings.dms.picker.conflictAncestor");
    return t("settings.dms.picker.conflictDescendant");
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-lg bg-card border-border text-foreground">
        <SheetHeader>
          <SheetTitle>{t("settings.dms.picker.title")}</SheetTitle>
          <SheetDescription className="text-muted-foreground">
            {t("settings.dms.picker.description")}
          </SheetDescription>
        </SheetHeader>

        <Breadcrumb className="shrink-0">
          <BreadcrumbList>
            <BreadcrumbItem>
              {isRoot ? (
                <BreadcrumbPage>{t("settings.dms.picker.rootLabel")}</BreadcrumbPage>
              ) : (
                <BreadcrumbLink asChild>
                  <button type="button" onClick={() => setCurrentPath(pathAtDepth(0))}>
                    {t("settings.dms.picker.rootLabel")}
                  </button>
                </BreadcrumbLink>
              )}
            </BreadcrumbItem>
            {segments.map((segment, i) => {
              const isLast = i === segments.length - 1;
              return (
                <span key={i} className="inline-flex items-center gap-1.5">
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage>{segment}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink asChild>
                        <button type="button" onClick={() => setCurrentPath(pathAtDepth(i + 1))}>
                          {segment}
                        </button>
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </span>
              );
            })}
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex-1 overflow-y-auto rounded-md border border-border">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("settings.dms.picker.loading")}
            </div>
          )}

          {!loading && error && (
            <div className="flex flex-col items-center gap-2 py-8 px-4 text-center text-sm text-red-400">
              <AlertCircle className="h-5 w-5" />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && entries.length === 0 && (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {t("settings.dms.picker.emptyFolder")}
            </div>
          )}

          {!loading &&
            !error &&
            entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                onClick={() => setCurrentPath(entry.path)}
                className="flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-left text-sm last:border-b-0 hover:bg-accent"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{entry.name}</span>
                </span>
                {entry.conflictType && (
                  <Badge variant={conflictBadgeVariant(entry.conflictType)} className="shrink-0">
                    {conflictLabel(entry.conflictType)}
                  </Badge>
                )}
              </button>
            ))}
        </div>

        <SheetFooter>
          <Button
            type="button"
            onClick={handleSelect}
            disabled={isRoot || hasConflict}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            {t("settings.dms.picker.selectButton")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
