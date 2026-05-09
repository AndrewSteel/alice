"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  sendMessage as apiSendMessage,
  streamChat,
  STREAM_API_URL,
  ChatMessage,
  fetchSessions,
  fetchSessionMessages,
  renameSessionApi,
  deleteSessionApi,
} from "@/services/api";
import { ActiveTool } from "@/components/Chat/ToolStatusChip";

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
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<ActiveTool[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // Ref to track if initial load happened
  const initialized = useRef(false);
  const abortRef = useRef<(() => void) | null>(null);
  const streamingSessionRef = useRef<string | null>(null);
  const isStreamingRef = useRef(false);

  // Cleanup: abort any pending stream when the hook unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.();
      abortRef.current = null;
    };
  }, []);

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
        clearLegacyStorage();
      })
      .catch(() => {
        // On error, sessions stay empty
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
      persisted: false,
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(id);
    return id;
  }, []);

  const selectSession = useCallback(
    (id: string) => {
      if (isStreamingRef.current && streamingSessionRef.current !== id) {
        const streamingSession = streamingSessionRef.current;
        const abort = abortRef.current;
        abortRef.current = null;
        streamingSessionRef.current = null;
        isStreamingRef.current = false;
        abort?.();
        setIsStreaming(false);
        setActiveTools([]);
        if (streamingSession) {
          setMessagesBySession((prev) => {
            const current = prev[streamingSession];
            if (!current || current.length === 0) return prev;
            const next = current.slice();
            const lastIdx = next.length - 1;
            const last = next[lastIdx];
            if (last.role !== "assistant") return prev;
            const suffix = last.content.length > 0 ? "\n\n*[Abgebrochen]*" : "*[Abgebrochen]*";
            next[lastIdx] = { ...last, content: last.content + suffix };
            return { ...prev, [streamingSession]: next };
          });
        }
      }
      setActiveSessionId(id);

      if (!messagesBySession[id]) {
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

    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s))
    );

    setSessions((prev) => {
      const session = prev.find((s) => s.id === id);
      if (session?.persisted) {
        renameSessionApi(id, trimmed).catch(() => {
          // keep optimistic
        });
      }
      return prev;
    });
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      if (id === streamingSessionRef.current) {
        const abort = abortRef.current;
        abortRef.current = null;
        streamingSessionRef.current = null;
        isStreamingRef.current = false;
        abort?.();
        setIsStreaming(false);
        setActiveTools([]);
      }

      const session = sessions.find((s) => s.id === id);

      setSessions((prev) => prev.filter((s) => s.id !== id));
      setMessagesBySession((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });

      if (session?.persisted) {
        deleteSessionApi(id).catch(() => {
          // session already removed from UI
        });
      }

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

  // ---------- Helpers shared by streaming + legacy paths ----------

  /**
   * Adds the user message and updates session metadata.
   * Returns the trimmed content + the conversation history before this turn
   * (used for the legacy non-streaming endpoint).
   */
  const beginUserTurn = useCallback(
    (
      sessionId: string,
      text: string
    ): { trimmed: string; history: Message[] } => {
      const trimmed = text.trim();
      const history = messagesBySession[sessionId] ?? [];

      const userMessage: Message = {
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      };

      setMessagesBySession((prev) => {
        const current = prev[sessionId] ?? [];
        return { ...prev, [sessionId]: [...current, userMessage] };
      });

      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const isFirstMessage =
            s.title === "Neuer Chat" &&
            !history.some((m) => m.role === "user");
          return {
            ...s,
            title: isFirstMessage ? trimmed.slice(0, 40) : s.title,
            updatedAt: new Date(),
            persisted: true,
          };
        })
      );

      return { trimmed, history };
    },
    [messagesBySession]
  );

  // ---------- Streaming send (PROJ-31) ----------

  const streamingSend = useCallback(
    (sessionId: string, text: string) => {
      const { trimmed } = beginUserTurn(sessionId, text);

      // Append an empty assistant placeholder; tokens will fill it in-place.
      setMessagesBySession((prev) => {
        const current = prev[sessionId] ?? [];
        const placeholder: Message = {
          role: "assistant",
          content: "",
          timestamp: new Date(),
        };
        return { ...prev, [sessionId]: [...current, placeholder] };
      });

      streamingSessionRef.current = sessionId;
      isStreamingRef.current = true;
      setIsStreaming(true);
      setActiveTools([]);

      const appendToken = (token: string) => {
        setMessagesBySession((prev) => {
          const current = prev[sessionId];
          if (!current || current.length === 0) return prev;
          const next = current.slice();
          const lastIdx = next.length - 1;
          const last = next[lastIdx];
          if (last.role !== "assistant") return prev;
          next[lastIdx] = { ...last, content: last.content + token };
          return { ...prev, [sessionId]: next };
        });
      };

      const handle = streamChat(sessionId, trimmed, {
        onToken: appendToken,
        onToolStart: (tool, status) => {
          setActiveTools((prev) => {
            if (prev.some((t) => t.tool === tool)) return prev;
            return [...prev, { tool, status }];
          });
          // If the current streaming placeholder already has content (LLM produced
          // text before the tool call), freeze it as a permanent bubble and open a
          // new empty placeholder for the post-tool answer.  If the placeholder is
          // still empty the LLM went straight to the tool — keep the single slot.
          setMessagesBySession((prev) => {
            const current = prev[sessionId] ?? [];
            if (current.length === 0) return prev;
            const last = current[current.length - 1];
            if (last.role !== "assistant" || last.content.length === 0) return prev;
            const newPlaceholder: Message = {
              role: "assistant",
              content: "",
              timestamp: new Date(),
            };
            return { ...prev, [sessionId]: [...current, newPlaceholder] };
          });
        },
        onToolEnd: (tool) => {
          setActiveTools((prev) => prev.filter((t) => t.tool !== tool));
        },
        onDone: () => {
          streamingSessionRef.current = null;
          isStreamingRef.current = false;
          abortRef.current = null;
          setIsStreaming(false);
          setActiveTools([]);
        },
        onError: (msg) => {
          // If we never received any content, surface the error in the
          // assistant placeholder; otherwise keep partial content and
          // append a separate error bubble.
          setMessagesBySession((prev) => {
            const current = prev[sessionId];
            if (!current || current.length === 0) return prev;
            const next = current.slice();
            const lastIdx = next.length - 1;
            const last = next[lastIdx];
            if (last.role === "assistant" && last.content.length === 0) {
              next[lastIdx] = { ...last, role: "error", content: msg };
            } else {
              next.push({
                role: "error",
                content: msg,
                timestamp: new Date(),
              });
            }
            return { ...prev, [sessionId]: next };
          });
          streamingSessionRef.current = null;
          isStreamingRef.current = false;
          abortRef.current = null;
          setIsStreaming(false);
          setActiveTools([]);
        },
      });

      abortRef.current = handle.abort;
    },
    [beginUserTurn]
  );

  const stopStreaming = useCallback(() => {
    if (!isStreamingRef.current) return;

    const sessionId = streamingSessionRef.current;
    const abort = abortRef.current;
    abortRef.current = null;
    streamingSessionRef.current = null;
    isStreamingRef.current = false;

    abort?.();
    setIsStreaming(false);
    setActiveTools([]);

    if (sessionId) {
      setMessagesBySession((prev) => {
        const current = prev[sessionId];
        if (!current || current.length === 0) return prev;
        const next = current.slice();
        const lastIdx = next.length - 1;
        const last = next[lastIdx];
        if (last.role !== "assistant") return prev;
        const suffix = last.content.length > 0 ? "\n\n*[Abgebrochen]*" : "*[Abgebrochen]*";
        next[lastIdx] = { ...last, content: last.content + suffix };
        return { ...prev, [sessionId]: next };
      });
    }
  }, []);

  // ---------- Legacy non-streaming send (fallback) ----------

  const legacySend = useCallback(
    async (sessionId: string, text: string) => {
      const { trimmed, history } = beginUserTurn(sessionId, text);

      setIsLoading(true);

      try {
        const allMessages: ChatMessage[] = [
          ...history
            .filter((m) => m.role !== "error")
            .map((m) => ({
              role: m.role as "user" | "assistant",
              content: m.content,
            })),
          { role: "user" as const, content: trimmed },
        ];

        const reply = await apiSendMessage(allMessages, sessionId);

        const assistantMessage: Message = {
          role: "assistant",
          content: reply,
          timestamp: new Date(),
        };

        setMessagesBySession((prev) => {
          const current = prev[sessionId] ?? [];
          return { ...prev, [sessionId]: [...current, assistantMessage] };
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
          const current = prev[sessionId] ?? [];
          return { ...prev, [sessionId]: [...current, errorMessage] };
        });
      } finally {
        setIsLoading(false);
      }
    },
    [beginUserTurn]
  );

  const sendMessage = useCallback(
    async (text: string) => {
      if (!activeSessionId || !text.trim()) return;
      if (isLoading || isStreaming) return;

      if (STREAM_API_URL) {
        streamingSend(activeSessionId, text);
      } else {
        await legacySend(activeSessionId, text);
      }
    },
    [activeSessionId, isLoading, isStreaming, legacySend, streamingSend]
  );

  return {
    sessions,
    sessionsLoaded,
    sessionsLoading,
    messagesLoading,
    activeSessionId,
    messages,
    isLoading,
    isStreaming,
    activeTools,
    createNewSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
    stopStreaming,
  };
}
