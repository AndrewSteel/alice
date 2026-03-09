"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  sendMessage as apiSendMessage,
  ChatMessage,
  fetchSessions,
  fetchSessionMessages,
  renameSessionApi,
  deleteSessionApi,
} from "@/services/api";

// ---------- Types ----------

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: Date;
  /** Whether this session exists in the backend (has at least one message). */
  persisted: boolean;
}

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
}

// ---------- localStorage migration ----------

const LEGACY_STORAGE_KEY = "alice_sessions";

function clearLegacyStorage(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // ignore
  }
}

// ---------- Hook ----------

export function useChatSessions() {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, Message[]>
  >({});
  const [isLoading, setIsLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // Ref to track if initial load happened
  const initialized = useRef(false);

  // Load sessions from backend API on mount
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    setSessionsLoading(true);

    fetchSessions()
      .then((apiSessions) => {
        const mapped: SessionMeta[] = apiSessions.map((s) => ({
          id: s.session_id,
          title: s.title || "Unbenannter Chat",
          updatedAt: new Date(s.last_activity || s.started_at),
          persisted: true,
        }));
        setSessions(mapped);
        // Clear legacy localStorage data (AC-C8)
        clearLegacyStorage();
      })
      .catch(() => {
        // On error, sessions stay empty; user sees error state
        // Legacy sessions are NOT restored -- backend is source of truth
      })
      .finally(() => {
        setSessionsLoading(false);
        setSessionsLoaded(true);
      });
  }, []);

  // Active session messages
  const messages = activeSessionId
    ? messagesBySession[activeSessionId] ?? []
    : [];

  // ---------- Actions ----------

  const createNewSession = useCallback(() => {
    const id = crypto.randomUUID();
    const newSession: SessionMeta = {
      id,
      title: "Neuer Chat",
      updatedAt: new Date(),
      persisted: false, // Not yet in backend (AC-C5)
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(id);
    return id;
  }, []);

  const selectSession = useCallback(
    (id: string) => {
      setActiveSessionId(id);

      // Load messages from backend if not cached yet (AC-C2, AC-C6)
      if (!messagesBySession[id]) {
        // Only fetch from backend if the session is persisted
        const session = sessions.find((s) => s.id === id);
        if (session?.persisted) {
          setMessagesLoading(true);
          fetchSessionMessages(id)
            .then((apiMessages) => {
              const mapped: Message[] = apiMessages.map((m) => ({
                role: m.role as "user" | "assistant",
                content: m.content,
                timestamp: new Date(m.timestamp),
              }));
              setMessagesBySession((prev) => ({ ...prev, [id]: mapped }));
            })
            .catch(() => {
              // On error (e.g. 403 from deleted session), show empty
              setMessagesBySession((prev) => ({ ...prev, [id]: [] }));
            })
            .finally(() => {
              setMessagesLoading(false);
            });
        }
      }
    },
    [messagesBySession, sessions]
  );

  const renameSession = useCallback((id: string, newTitle: string) => {
    const trimmed = newTitle.trim();
    if (!trimmed) return;

    // Optimistic update (AC-C3)
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s))
    );

    // Send to backend if persisted
    setSessions((prev) => {
      const session = prev.find((s) => s.id === id);
      if (session?.persisted) {
        renameSessionApi(id, trimmed).catch(() => {
          // Revert on error -- but for simplicity we keep optimistic
        });
      }
      return prev;
    });
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      // Check if persisted before removing from state
      const session = sessions.find((s) => s.id === id);

      // Remove from RAM state (AC-C4)
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setMessagesBySession((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });

      // Send to backend if persisted
      if (session?.persisted) {
        deleteSessionApi(id).catch(() => {
          // Delete failed -- session is already removed from UI
          // On next reload it will reappear from backend
        });
      }

      // If the deleted session was active, create a new one (AC-C7)
      if (activeSessionId === id) {
        const newId = crypto.randomUUID();
        const newSession: SessionMeta = {
          id: newId,
          title: "Neuer Chat",
          updatedAt: new Date(),
          persisted: false,
        };
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newId);
      }
    },
    [activeSessionId, sessions]
  );

  const sendMessage = useCallback(
    async (text: string) => {
      if (!activeSessionId || !text.trim() || isLoading) return;

      const userMessage: Message = {
        role: "user",
        content: text.trim(),
        timestamp: new Date(),
      };

      // Add user message optimistically
      setMessagesBySession((prev) => {
        const current = prev[activeSessionId] ?? [];
        return { ...prev, [activeSessionId]: [...current, userMessage] };
      });

      // Update session title (first user message = title) and updatedAt
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeSessionId) return s;
          const isFirstMessage =
            s.title === "Neuer Chat" &&
            !(messagesBySession[activeSessionId] ?? []).some(
              (m) => m.role === "user"
            );
          return {
            ...s,
            title: isFirstMessage
              ? text.trim().slice(0, 40)
              : s.title,
            updatedAt: new Date(),
            // After first message, the chat-handler will create the session in DB
            // Mark as persisted so future operations go to backend
            persisted: true,
          };
        })
      );

      setIsLoading(true);

      try {
        // Build OpenAI-compatible messages array for the API
        const currentMessages = messagesBySession[activeSessionId] ?? [];
        const allMessages: ChatMessage[] = [
          ...currentMessages
            .filter((m) => m.role !== "error")
            .map((m) => ({
              role: m.role as "user" | "assistant",
              content: m.content,
            })),
          { role: "user" as const, content: text.trim() },
        ];

        const reply = await apiSendMessage(allMessages, activeSessionId);

        const assistantMessage: Message = {
          role: "assistant",
          content: reply,
          timestamp: new Date(),
        };

        setMessagesBySession((prev) => {
          const current = prev[activeSessionId] ?? [];
          return { ...prev, [activeSessionId]: [...current, assistantMessage] };
        });
      } catch (err) {
        const errorMessage: Message = {
          role: "error",
          content:
            err instanceof Error
              ? err.message
              : "Ein unbekannter Fehler ist aufgetreten.",
          timestamp: new Date(),
        };

        setMessagesBySession((prev) => {
          const current = prev[activeSessionId] ?? [];
          return { ...prev, [activeSessionId]: [...current, errorMessage] };
        });
      } finally {
        setIsLoading(false);
      }
    },
    [activeSessionId, isLoading, messagesBySession]
  );

  return {
    sessions,
    sessionsLoaded,
    sessionsLoading,
    messagesLoading,
    activeSessionId,
    messages,
    isLoading,
    createNewSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
  };
}
