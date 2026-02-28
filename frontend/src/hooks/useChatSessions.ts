"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { sendMessage as apiSendMessage, ChatMessage } from "@/services/api";

// ---------- Types ----------

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: Date;
}

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
}

// ---------- localStorage helpers ----------

const STORAGE_KEY = "alice_sessions";

function loadSessions(): SessionMeta[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SessionMeta[];
    return parsed.map((s) => ({ ...s, updatedAt: new Date(s.updatedAt) }));
  } catch {
    return [];
  }
}

function saveSessions(sessions: SessionMeta[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

// ---------- Hook ----------

export function useChatSessions() {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, Message[]>
  >({});
  const [isLoading, setIsLoading] = useState(false);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);

  // Ref to track if initial load happened
  const initialized = useRef(false);

  // Load sessions from localStorage on mount
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const stored = loadSessions();
    if (stored.length > 0) {
      setSessions(stored);
    }
    setSessionsLoaded(true);
  }, []);

  // Persist sessions to localStorage whenever they change
  useEffect(() => {
    if (initialized.current && sessions.length > 0) {
      saveSessions(sessions);
    } else if (initialized.current && sessions.length === 0) {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [sessions]);

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
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(id);
    return id;
  }, []);

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setMessagesBySession((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });

      // If the deleted session was active, create a new one
      if (activeSessionId === id) {
        const newId = crypto.randomUUID();
        const newSession: SessionMeta = {
          id: newId,
          title: "Neuer Chat",
          updatedAt: new Date(),
        };
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newId);
      }
    },
    [activeSessionId]
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
    activeSessionId,
    messages,
    isLoading,
    createNewSession,
    selectSession,
    deleteSession,
    sendMessage,
  };
}
