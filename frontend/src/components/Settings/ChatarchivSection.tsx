"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n/config";
import { formatDateTimeShort, formatDateTimeFull } from "@/i18n/format";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MessageRenderer } from "@/components/Chat/MessageRenderer";
import { Message } from "@/components/Chat/types";
import {
  AdminMessageItem,
  AdminSessionItem,
  deleteAdminSession,
  fetchAdminSessionMessages,
  fetchAdminSessions,
} from "@/services/api";

// ---------- Helpers ----------

function sourceLabel(source: string | null): string {
  if (!source) return "—";
  if (source === "webapp_cc") return i18n.t("settings.chatArchive.sourceWebappCc");
  if (source === "webapp_mic") return i18n.t("settings.chatArchive.sourceWebappMic");
  if (source === "esphome") return i18n.t("settings.chatArchive.sourceEsphome");
  if (source.startsWith("esphome:"))
    return i18n.t("settings.chatArchive.sourceEsphomeSuffix", { name: source.slice(8) });
  return source;
}

function typeLabel(sessionType: string | null): string {
  return sessionType === "ha_only"
    ? i18n.t("settings.chatArchive.typeHaOnly")
    : i18n.t("settings.chatArchive.typeLlm");
}

function mapAdminMessage(m: AdminMessageItem): Message | null {
  const base = {
    id: String(m.id),
    content: m.content,
    createdAt: new Date(m.timestamp).getTime(),
  };

  if (m.msg_type) {
    switch (m.msg_type) {
      case "user_text":
      case "user_stt":
        return { ...base, role: "user" };
      case "llm_response":
        return { ...base, role: "assistant" };
      case "llm_thinking":
        return { ...base, role: "thinking" };
      case "ha_result":
      case "tool_result":
        return { ...base, role: "tool_call", toolStatus: "done" };
    }
  }

  // Legacy (no msg_type): use role column
  if (m.role === "user") return { ...base, role: "user" };
  if (m.role === "assistant") return { ...base, role: "assistant" };
  return null;
}

// ---------- DeleteDialog ----------

interface DeleteDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteDialog({ open, onConfirm, onCancel }: DeleteDialogProps) {
  const { t } = useTranslation();
  return (
    <AlertDialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <AlertDialogContent className="bg-card border-border">
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.chatArchive.deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("settings.chatArchive.deleteDesc")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel className="border-border" onClick={onCancel}>
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-red-600 hover:bg-red-700"
          >
            {t("common.delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---------- ListView ----------

interface ListViewProps {
  onSelectSession: (id: string) => void;
}

function ListView({ onSelectSession }: ListViewProps) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<AdminSessionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const limit = 20;

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const data = await fetchAdminSessions(p, limit);
      setSessions(data.sessions);
      setTotal(data.total);
      setPage(p);
    } catch {
      // ignore — list stays empty
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(1);
  }, [load]);

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAdminSession(deleteTarget);
      await load(page);
    } catch {
      // ignore
    } finally {
      setDeleteTarget(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div>
      <h2 className="text-base font-semibold mb-4 text-foreground">
        {t("settings.chatArchive.title")}
      </h2>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center">
          {t("settings.chatArchive.empty")}
        </p>
      ) : (
        <>
          <div className="rounded-md border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">{t("settings.chatArchive.table.user")}</TableHead>
                  <TableHead className="text-muted-foreground">{t("settings.chatArchive.table.date")}</TableHead>
                  <TableHead className="text-muted-foreground">{t("settings.chatArchive.table.type")}</TableHead>
                  <TableHead className="text-muted-foreground">{t("settings.chatArchive.table.title")}</TableHead>
                  <TableHead className="text-muted-foreground text-right">
                    {t("settings.chatArchive.table.messages")}
                  </TableHead>
                  <TableHead className="text-muted-foreground">{t("settings.chatArchive.table.source")}</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow
                    key={s.session_id}
                    className="border-border hover:bg-accent/50 cursor-pointer"
                    onClick={() => onSelectSession(s.session_id)}
                  >
                    <TableCell className="font-medium text-foreground">
                      {s.username}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm whitespace-nowrap">
                      {formatDateTimeShort(s.started_at)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          s.session_type === "ha_only" ? "outline" : "secondary"
                        }
                        className="text-xs"
                      >
                        {typeLabel(s.session_type)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-foreground text-sm max-w-[200px] truncate">
                      {s.title ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm text-right">
                      {s.message_count}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {sourceLabel(s.source)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-red-400"
                        aria-label={t("settings.chatArchive.deleteAria")}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteTarget(s.session_id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex justify-center">
              <Pagination>
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      onClick={() => page > 1 && void load(page - 1)}
                      className={
                        page <= 1
                          ? "pointer-events-none opacity-50"
                          : "cursor-pointer"
                      }
                    />
                  </PaginationItem>
                  <PaginationItem>
                    <span className="px-4 py-2 text-sm text-muted-foreground">
                      {t("settings.chatArchive.page", { page, total: totalPages })}
                    </span>
                  </PaginationItem>
                  <PaginationItem>
                    <PaginationNext
                      onClick={() =>
                        page < totalPages && void load(page + 1)
                      }
                      className={
                        page >= totalPages
                          ? "pointer-events-none opacity-50"
                          : "cursor-pointer"
                      }
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          )}
        </>
      )}

      <DeleteDialog
        open={!!deleteTarget}
        onConfirm={() => void handleDeleteConfirm()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

// ---------- DetailView ----------

interface DetailViewProps {
  sessionId: string;
  onBack: () => void;
}

function DetailView({ sessionId, onBack }: DetailViewProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<{
    session: AdminSessionItem;
    messages: AdminMessageItem[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  useEffect(() => {
    setLoading(true);
    setNotFound(false);
    fetchAdminSessionMessages(sessionId)
      .then(setData)
      .catch((err: Error) => {
        if (err.message.includes("404")) setNotFound(true);
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleDeleteConfirm = async () => {
    try {
      await deleteAdminSession(sessionId);
      onBack();
    } catch {
      setShowDelete(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (notFound || !data) {
    return (
      <div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onBack}
          className="mb-4 text-muted-foreground"
        >
          <ChevronLeft className="h-4 w-4 mr-1" />
          {t("settings.chatArchive.back")}
        </Button>
        <p className="text-sm text-muted-foreground">{t("settings.chatArchive.notFound")}</p>
      </div>
    );
  }

  const { session, messages } = data;
  const mappedMessages: Message[] = messages.flatMap((m) => {
    const msg = mapAdminMessage(m);
    return msg ? [msg] : [];
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={onBack}
          className="text-muted-foreground"
        >
          <ChevronLeft className="h-4 w-4 mr-1" />
          {t("settings.chatArchive.back")}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground hover:text-red-400"
          onClick={() => setShowDelete(true)}
          aria-label={t("settings.chatArchive.deleteAria")}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      {/* Metadata */}
      <div className="rounded-md border border-border bg-card/50 p-4 mb-4 text-sm space-y-1">
        <div className="flex gap-4 flex-wrap">
          <span className="text-muted-foreground">
            {t("settings.chatArchive.metaUser")}:{" "}
            <span className="text-foreground">{session.username}</span>
          </span>
          <span className="text-muted-foreground">
            {t("settings.chatArchive.metaSource")}:{" "}
            <span className="text-foreground">{sourceLabel(session.source)}</span>
          </span>
          <span className="text-muted-foreground">
            {t("settings.chatArchive.metaType")}:{" "}
            <span className="text-foreground">
              {typeLabel(session.session_type)}
            </span>
          </span>
        </div>
        <div className="text-muted-foreground">
          {t("settings.chatArchive.metaStart")}:{" "}
          <span className="text-foreground">
            {formatDateTimeFull(session.started_at)}
          </span>
        </div>
        <div className="text-muted-foreground text-xs">
          {t("settings.chatArchive.metaId")}: {session.session_id}
        </div>
      </div>

      {/* Messages */}
      {mappedMessages.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-8">
          {t("settings.chatArchive.noMessages")}
        </p>
      ) : (
        <div className="space-y-2">
          {mappedMessages.map((msg) => (
            <MessageRenderer key={msg.id} message={msg} />
          ))}
        </div>
      )}

      <DeleteDialog
        open={showDelete}
        onConfirm={() => void handleDeleteConfirm()}
        onCancel={() => setShowDelete(false)}
      />
    </div>
  );
}

// ---------- ChatarchivSection ----------

export function ChatarchivSection() {
  const [view, setView] = useState<"list" | "detail">("list");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  function handleSelect(id: string) {
    setSelectedId(id);
    setView("detail");
  }

  function handleBack() {
    setView("list");
    setSelectedId(null);
  }

  if (view === "detail" && selectedId) {
    return <DetailView sessionId={selectedId} onBack={handleBack} />;
  }

  return <ListView onSelectSession={handleSelect} />;
}
