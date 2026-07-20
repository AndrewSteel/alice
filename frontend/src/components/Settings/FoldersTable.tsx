"use client";

import { useMemo } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { GripVertical, Loader2, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { DmsFolder } from "@/services/dms";

interface FoldersTableProps {
  folders: DmsFolder[];
  isReordering: boolean;
  onEdit: (folder: DmsFolder) => void;
  onDelete: (folder: DmsFolder) => void;
  onToggle: (folder: DmsFolder) => void;
  onReorder: (reorderedFolders: DmsFolder[]) => void;
}

function truncate(text: string | null, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "..." : text;
}

// ---------- Sortable Row (Desktop) ----------

interface SortableDesktopRowProps {
  folder: DmsFolder;
  isReordering: boolean;
  onEdit: (folder: DmsFolder) => void;
  onDelete: (folder: DmsFolder) => void;
  onToggle: (folder: DmsFolder) => void;
}

function SortableDesktopRow({
  folder,
  isReordering,
  onEdit,
  onDelete,
  onToggle,
}: SortableDesktopRowProps) {
  const { t } = useTranslation();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: folder.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <TableRow
      ref={setNodeRef}
      style={style}
      className={`border-border hover:bg-accent/50 ${
        isDragging ? "bg-card opacity-80 shadow-lg z-50 relative" : ""
      }`}
    >
      <TableCell className="text-foreground font-mono text-sm max-w-[300px] truncate">
        {folder.path}
      </TableCell>
      <TableCell>
        <TypeBadge type={folder.suggested_type} />
      </TableCell>
      <TableCell className="text-foreground text-sm max-w-[200px]">
        {truncate(folder.description, 60)}
      </TableCell>
      <TableCell className="text-center">
        <Switch
          checked={folder.enabled}
          onCheckedChange={() => onToggle(folder)}
          aria-label={folder.enabled
            ? t("settings.dms.table.disableAria", { path: folder.path })
            : t("settings.dms.table.enableAria", { path: folder.path })}
        />
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onEdit(folder)}
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                aria-label={t("settings.dms.table.editAria", { path: folder.path })}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("settings.dms.table.edit")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onDelete(folder)}
                className="h-8 w-8 text-muted-foreground hover:text-red-400"
                aria-label={t("settings.dms.table.deleteAria", { path: folder.path })}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("settings.dms.table.delete")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                {...attributes}
                {...listeners}
                className="h-8 w-8 flex items-center justify-center text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing rounded-md hover:bg-accent/50 transition-colors touch-none"
                aria-label={t("settings.dms.table.moveAria", { path: folder.path })}
              >
                {isReordering ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <GripVertical className="h-4 w-4" />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent>{t("settings.dms.table.move")}</TooltipContent>
          </Tooltip>
        </div>
      </TableCell>
    </TableRow>
  );
}

// ---------- Sortable Row (Mobile) ----------

interface SortableMobileRowProps {
  folder: DmsFolder;
  isReordering: boolean;
  onEdit: (folder: DmsFolder) => void;
  onDelete: (folder: DmsFolder) => void;
  onToggle: (folder: DmsFolder) => void;
}

function SortableMobileRow({
  folder,
  isReordering,
  onEdit,
  onDelete,
  onToggle,
}: SortableMobileRowProps) {
  const { t } = useTranslation();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: folder.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`p-4 space-y-3 ${
        isDragging ? "bg-card opacity-80 shadow-lg z-50 relative" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <button
            {...attributes}
            {...listeners}
            className="shrink-0 h-8 w-8 flex items-center justify-center text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing rounded-md touch-none"
            aria-label={t("settings.dms.table.moveAria", { path: folder.path })}
          >
            {isReordering ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <GripVertical className="h-4 w-4" />
            )}
          </button>
          <p className="text-sm font-mono text-foreground break-all">{folder.path}</p>
        </div>
        <Switch
          checked={folder.enabled}
          onCheckedChange={() => onToggle(folder)}
          aria-label={folder.enabled
            ? t("settings.dms.table.disableAria", { path: folder.path })
            : t("settings.dms.table.enableAria", { path: folder.path })}
          className="shrink-0"
        />
      </div>
      <div className="flex items-center gap-2 pl-10">
        <TypeBadge type={folder.suggested_type} />
        {folder.description && (
          <span className="text-xs text-muted-foreground truncate">
            {truncate(folder.description, 40)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 pl-10">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onEdit(folder)}
          className="h-7 gap-1 text-muted-foreground hover:text-foreground px-2"
        >
          <Pencil className="h-3.5 w-3.5" />
          {t("settings.dms.table.edit")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(folder)}
          className="h-7 gap-1 text-muted-foreground hover:text-red-400 px-2"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t("settings.dms.table.delete")}
        </Button>
      </div>
    </div>
  );
}

// ---------- Main Table Component ----------

export function FoldersTable({
  folders,
  isReordering,
  onEdit,
  onDelete,
  onToggle,
  onReorder,
}: FoldersTableProps) {
  const { t } = useTranslation();
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const folderIds = useMemo(() => folders.map((f) => f.id), [folders]);

  function handleDragEnd(event: DragEndEvent) {
    if (isReordering) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = folders.findIndex((f) => f.id === active.id);
    const newIndex = folders.findIndex((f) => f.id === over.id);

    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(folders, oldIndex, newIndex);
    onReorder(reordered);
  }

  return (
    <TooltipProvider>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
        modifiers={[restrictToVerticalAxis]}
      >
        <SortableContext items={folderIds} strategy={verticalListSortingStrategy}>
          <div className="rounded-lg border border-border overflow-hidden">
            {/* Desktop table */}
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="text-muted-foreground">{t("settings.dms.table.path")}</TableHead>
                    <TableHead className="text-muted-foreground">{t("settings.dms.table.type")}</TableHead>
                    <TableHead className="text-muted-foreground">{t("settings.dms.table.description")}</TableHead>
                    <TableHead className="text-muted-foreground text-center">{t("settings.dms.table.status")}</TableHead>
                    <TableHead className="text-muted-foreground text-right">{t("settings.dms.table.actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {folders.map((folder) => (
                    <SortableDesktopRow
                      key={folder.id}
                      folder={folder}
                      isReordering={isReordering}
                      onEdit={onEdit}
                      onDelete={onDelete}
                      onToggle={onToggle}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Mobile card list */}
            <div className="md:hidden divide-y divide-border">
              {folders.map((folder) => (
                <SortableMobileRow
                  key={folder.id}
                  folder={folder}
                  isReordering={isReordering}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onToggle={onToggle}
                />
              ))}
            </div>
          </div>
        </SortableContext>
      </DndContext>
    </TooltipProvider>
  );
}

function TypeBadge({ type }: { type: string | null }) {
  const { t } = useTranslation();
  if (!type) {
    return (
      <Badge variant="outline" className="border-border text-muted-foreground text-xs">
        {t("settings.dms.table.auto")}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-blue-900/40 text-blue-300 border-blue-800 text-xs">
      {type}
    </Badge>
  );
}
