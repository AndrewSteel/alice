"use client";

import { Pencil, Trash2 } from "lucide-react";
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
  onEdit: (folder: DmsFolder) => void;
  onDelete: (folder: DmsFolder) => void;
  onToggle: (folder: DmsFolder) => void;
}

function truncate(text: string | null, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "..." : text;
}

export function FoldersTable({ folders, onEdit, onDelete, onToggle }: FoldersTableProps) {
  return (
    <TooltipProvider>
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
                <TableRow key={folder.id} className="border-gray-700 hover:bg-gray-800/50">
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
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {/* Mobile card list */}
        <div className="md:hidden divide-y divide-gray-700">
          {folders.map((folder) => (
            <div key={folder.id} className="p-4 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-mono text-gray-100 break-all">{folder.path}</p>
                <Switch
                  checked={folder.enabled}
                  onCheckedChange={() => onToggle(folder)}
                  aria-label={`Ordner ${folder.path} ${folder.enabled ? "deaktivieren" : "aktivieren"}`}
                  className="shrink-0"
                />
              </div>
              <div className="flex items-center gap-2">
                <TypeBadge type={folder.suggested_type} />
                {folder.description && (
                  <span className="text-xs text-gray-400 truncate">
                    {truncate(folder.description, 40)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
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
          ))}
        </div>
      </div>
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
