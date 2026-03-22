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
      className={`border-gray-700 hover:bg-gray-800/50 ${
        isDragging ? "bg-gray-800 opacity-80 shadow-lg z-50 relative" : ""
      }`}
    >
      <TableCell className="text-gray-100 font-mono text-sm max-w-[300px] truncate">
        {folder.path}
      </TableCell>
      <TableCell>
        <TypeBadge type={folder.suggested_type} />
      </TableCell>
      <TableCell className="text-gray-300 text-sm max-w-[200px]">
        {truncate(folder.description, 60)}
      </TableCell>
      <TableCell className="text-center">
        <Switch
          checked={folder.enabled}
          onCheckedChange={() => onToggle(folder)}
          aria-label={`Ordner ${folder.path} ${folder.enabled ? "deaktivieren" : "aktivieren"}`}
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
                className="h-8 w-8 text-gray-400 hover:text-gray-100"
                aria-label={`Ordner ${folder.path} bearbeiten`}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Bearbeiten</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onDelete(folder)}
                className="h-8 w-8 text-gray-400 hover:text-red-400"
                aria-label={`Ordner ${folder.path} loeschen`}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Loeschen</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                {...attributes}
                {...listeners}
                className="h-8 w-8 flex items-center justify-center text-gray-400 hover:text-gray-100 cursor-grab active:cursor-grabbing rounded-md hover:bg-gray-700/50 transition-colors touch-none"
                aria-label={`Ordner ${folder.path} verschieben`}
              >
                {isReordering ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <GripVertical className="h-4 w-4" />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent>Verschieben</TooltipContent>
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
        isDragging ? "bg-gray-800 opacity-80 shadow-lg z-50 relative" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <button
            {...attributes}
            {...listeners}
            className="shrink-0 h-8 w-8 flex items-center justify-center text-gray-400 hover:text-gray-100 cursor-grab active:cursor-grabbing rounded-md touch-none"
            aria-label={`Ordner ${folder.path} verschieben`}
          >
            {isReordering ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <GripVertical className="h-4 w-4" />
            )}
          </button>
          <p className="text-sm font-mono text-gray-100 break-all">{folder.path}</p>
        </div>
        <Switch
          checked={folder.enabled}
          onCheckedChange={() => onToggle(folder)}
          aria-label={`Ordner ${folder.path} ${folder.enabled ? "deaktivieren" : "aktivieren"}`}
          className="shrink-0"
        />
      </div>
      <div className="flex items-center gap-2 pl-10">
        <TypeBadge type={folder.suggested_type} />
        {folder.description && (
          <span className="text-xs text-gray-400 truncate">
            {truncate(folder.description, 40)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 pl-10">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onEdit(folder)}
          className="h-7 gap-1 text-gray-400 hover:text-gray-100 px-2"
        >
          <Pencil className="h-3.5 w-3.5" />
          Bearbeiten
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(folder)}
          className="h-7 gap-1 text-gray-400 hover:text-red-400 px-2"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Loeschen
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
          <div className="rounded-lg border border-gray-700 overflow-hidden">
            {/* Desktop table */}
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-700 hover:bg-transparent">
                    <TableHead className="text-gray-400">Pfad</TableHead>
                    <TableHead className="text-gray-400">Typ</TableHead>
                    <TableHead className="text-gray-400">Beschreibung</TableHead>
                    <TableHead className="text-gray-400 text-center">Status</TableHead>
                    <TableHead className="text-gray-400 text-right">Aktionen</TableHead>
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
            <div className="md:hidden divide-y divide-gray-700">
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
  if (!type) {
    return (
      <Badge variant="outline" className="border-gray-600 text-gray-400 text-xs">
        auto
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-blue-900/40 text-blue-300 border-blue-800 text-xs">
      {type}
    </Badge>
  );
}
