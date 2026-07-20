"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  sendMessage as apiSendMessage,
  streamChat,
  STREAM_API_URL,
  ChatMessage,
  fetchSessions,
  fetchSessionMessages,
  renameSessionApi,
  deleteSessionApi,
  VisionResult,
} from "@/services/api";
import { Message } from "@/components/Chat/types";
import i18n from "@/i18n/config";

// ---------- Types ----------

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: Date;
  /** Whether this session exists in the backend (has at least one message). */
  persisted: boolean;
}

// ---------- Message state reducer ----------
//
// Single source of truth for `messagesBySession` (Record<sessionId, Message[]>).
// Every message-state mutation flows through exactly one action here — one
// action type per SSE event plus the session-lifecycle actions. State stays
// partitioned per `sessionId`, so a stream for one session never touches
// another session's messages.
//
// The reducer is pure w.r.t. non-deterministic sources: ids (`newId()`) and
// timestamps (`Date.now()`) are generated at the dispatch site and passed in
// via the action payload, never computed inside a case. `i18n.t(...)` is a
// deterministic lookup and stays inside the case that owns the display text.
//
// Extensibility: a new SSE event type is added by (1) one new action variant,
// (2) one new `case` here, and (3) one new renderer. No existing case changes.

type MessagesState = Record<string, Message[]>;

type MessagesAction =
  // Session lifecycle
  | { type: "reload"; sessionId: string; messages: Message[] }
  | { type: "delete_session"; sessionId: string }
  // Turn lifecycle
  | {
      type: "user_message";
      sessionId: string;
      id: string;
      content: string;
      createdAt: number;
    }
  | {
      type: "assistant_placeholder";
      sessionId: string;
      id: string;
      createdAt: number;
    }
  // SSE events
  | {
      type: "token";
      sessionId: string;
      token: string;
      id: string;
      createdAt: number;
    }
  | {
      type: "thinking";
      sessionId: string;
      chunk: string;
      id: string;
      createdAt: number;
    }
  | {
      type: "tool_start";
      sessionId: string;
      id: string;
      createdAt: number;
      tool: string;
      status?: string;
    }
  | { type: "tool_end"; sessionId: string; tool: string; summary?: string }
  | { type: "done"; sessionId: string }
  | {
      type: "error";
      sessionId: string;
      errMsg: string;
      id: string;
      createdAt: number;
    }
  // Stream abort (Stop button / session switch mid-stream)
  | {
      type: "abort";
      sessionId: string;
      statusId: string;
      statusCreatedAt: number;
    }
  // Legacy non-streaming send (fallback)
  | {
      type: "assistant_message";
      sessionId: string;
      id: string;
      content: string;
      createdAt: number;
    }
  | {
      type: "error_message";
      sessionId: string;
      id: string;
      content: string;
      createdAt: number;
    };

function messagesReducer(
  state: MessagesState,
  action: MessagesAction
): MessagesState {
  switch (action.type) {
    // Replace a session's whole message list (session-reload / reset-to-empty).
    case "reload":
      return { ...state, [action.sessionId]: action.messages };

    case "delete_session": {
      const next = { ...state };
      delete next[action.sessionId];
      return next;
    }

    case "user_message": {
      const current = state[action.sessionId] ?? [];
      const userMessage: Message = {
        id: action.id,
        role: "user",
        content: action.content,
        createdAt: action.createdAt,
      };
      return { ...state, [action.sessionId]: [...current, userMessage] };
    }

    // Empty assistant bubble; tokens fill it in-place.
    case "assistant_placeholder": {
      const current = state[action.sessionId] ?? [];
      const placeholder: Message = {
        id: action.id,
        role: "assistant",
        content: "",
        createdAt: action.createdAt,
        streaming: true,
      };
      return { ...state, [action.sessionId]: [...current, placeholder] };
    }

    // Append a token to the last assistant message.
    // PROJ-37: thinking→token transition opens a NEW assistant bubble so
    // reasoning text and answer text stay in separate messages. Anything
    // else (tool_call, error, …) also opens a new assistant bubble.
    case "token": {
      const current = state[action.sessionId];
      if (!current || current.length === 0) return state;
      const next = current.slice();
      const lastIdx = next.length - 1;
      const last = next[lastIdx];

      if (last.role === "assistant") {
        next[lastIdx] = { ...last, content: last.content + action.token };
      } else {
        // Close an open thinking-message before opening the answer bubble.
        if (last.role === "thinking" && last.streaming) {
          next[lastIdx] = { ...last, streaming: false };
        }
        next.push({
          id: action.id,
          role: "assistant",
          content: action.token,
          createdAt: action.createdAt,
          streaming: true,
        });
      }
      return { ...state, [action.sessionId]: next };
    }

    // PROJ-37: thinking event — either convert the empty assistant placeholder
    // to a thinking bubble, append to the last thinking message, or insert a
    // new one. This keeps the chat tidy (no empty assistant + thinking pair).
    case "thinking": {
      const current = state[action.sessionId];
      if (!current || current.length === 0) return state;
      const next = current.slice();
      const lastIdx = next.length - 1;
      const last = next[lastIdx];

      if (
        last.role === "assistant" &&
        last.content.length === 0 &&
        last.streaming
      ) {
        // In-place conversion of the empty placeholder.
        next[lastIdx] = {
          ...last,
          role: "thinking",
          content: action.chunk,
        };
      } else if (last.role === "thinking" && last.streaming) {
        next[lastIdx] = { ...last, content: last.content + action.chunk };
      } else {
        next.push({
          id: action.id,
          role: "thinking",
          content: action.chunk,
          createdAt: action.createdAt,
          streaming: true,
        });
      }
      return { ...state, [action.sessionId]: next };
    }

    // tool_start: insert a new tool_call message (status=running).
    case "tool_start": {
      const current = state[action.sessionId] ?? [];
      // Close streaming on the previous assistant OR thinking message so the
      // cursor moves to the tool_call line. PROJ-37: also handles the case
      // where Ollama interleaves a tool call inside a thinking block.
      const closed = current.map((m, i) =>
        i === current.length - 1 &&
        (m.role === "assistant" || m.role === "thinking") &&
        m.streaming
          ? { ...m, streaming: false }
          : m
      );
      const toolMsg: Message = {
        id: action.id,
        role: "tool_call",
        content: action.status ?? "",
        createdAt: action.createdAt,
        toolName: action.tool,
        toolStatus: "running",
      };
      return { ...state, [action.sessionId]: [...closed, toolMsg] };
    }

    // tool_end: update the matching running tool_call to status=done.
    // PROJ-37: when the backend ships a `summary`, also overwrite the
    // tool_call message content with it (e.g. "3 Dokumente gefunden").
    case "tool_end": {
      const current = state[action.sessionId];
      if (!current) return state;
      const next = current.slice();
      for (let i = next.length - 1; i >= 0; i--) {
        const m = next[i];
        if (
          m.role === "tool_call" &&
          m.toolName === action.tool &&
          m.toolStatus === "running"
        ) {
          next[i] = {
            ...m,
            toolStatus: "done",
            content:
              action.summary && action.summary.length > 0
                ? action.summary
                : m.content,
          };
          break;
        }
      }
      return { ...state, [action.sessionId]: next };
    }

    // done: clear the streaming flag on the last streaming message.
    case "done": {
      const current = state[action.sessionId];
      if (!current || current.length === 0) return state;
      const next = current.slice();
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].streaming) {
          next[i] = { ...next[i], streaming: false };
          break;
        }
      }
      return { ...state, [action.sessionId]: next };
    }

    case "error": {
      const current = state[action.sessionId];
      if (!current || current.length === 0) return state;
      const next = current.slice();
      const lastIdx = next.length - 1;
      const last = next[lastIdx];

      // Mark any in-flight tool_call as errored.
      for (let i = next.length - 1; i >= 0; i--) {
        const m = next[i];
        if (m.role === "tool_call" && m.toolStatus === "running") {
          next[i] = { ...m, toolStatus: "error" };
          break;
        }
      }

      // If the last message is the empty assistant placeholder, replace it
      // with the error; otherwise push a new error message.
      if (last.role === "assistant" && last.content.length === 0) {
        next[lastIdx] = {
          ...last,
          role: "error",
          content: action.errMsg,
          streaming: false,
        };
      } else {
        // Stop streaming flag on assistant first.
        if (last.role === "assistant" && last.streaming) {
          next[lastIdx] = { ...last, streaming: false };
        }
        next.push({
          id: action.id,
          role: "error",
          content: action.errMsg,
          createdAt: action.createdAt,
        });
      }
      return { ...state, [action.sessionId]: next };
    }

    case "abort": {
      const current = state[action.sessionId];
      if (!current || current.length === 0) return state;
      const next = current.slice();

      // Stop any in-flight tool_call spinners — they would otherwise stay
      // running forever after an abort.
      for (let i = 0; i < next.length; i++) {
        const m = next[i];
        if (m.role === "tool_call" && m.toolStatus === "running") {
          next[i] = { ...m, toolStatus: "error" };
        }
        // PROJ-37: close any open thinking-message so it stops blinking.
        if (m.role === "thinking" && m.streaming) {
          next[i] = { ...m, streaming: false };
        }
      }

      const lastIdx = next.length - 1;
      const last = next[lastIdx];
      // Mark last assistant message as aborted; otherwise append a status message.
      if (last.role === "assistant") {
        const marker = i18n.t("chat.abortedMarker");
        const suffix = last.content.length > 0 ? `\n\n${marker}` : marker;
        next[lastIdx] = {
          ...last,
          content: last.content + suffix,
          streaming: false,
        };
      } else {
        next.push({
          id: action.statusId,
          role: "status",
          content: i18n.t("chat.aborted"),
          createdAt: action.statusCreatedAt,
        });
      }
      return { ...state, [action.sessionId]: next };
    }

    case "assistant_message": {
      const current = state[action.sessionId] ?? [];
      const assistantMessage: Message = {
        id: action.id,
        role: "assistant",
        content: action.content,
        createdAt: action.createdAt,
      };
      return { ...state, [action.sessionId]: [...current, assistantMessage] };
    }

    case "error_message": {
      const current = state[action.sessionId] ?? [];
      const errorMessage: Message = {
        id: action.id,
        role: "error",
        content: action.content,
        createdAt: action.createdAt,
      };
      return { ...state, [action.sessionId]: [...current, errorMessage] };
    }

    default:
      return state;
  }
}

// ---------- Helpers ----------

const LEGACY_STORAGE_KEY = "alice_sessions";

function clearLegacyStorage(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // ignore
  }
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ---------- Hook ----------

export interface UseChatSessionsOptions {
  onVisionResults?: (results: VisionResult[]) => void;
  onTextResponse?: () => void;
}

export function useChatSessions(options: UseChatSessionsOptions = {}) {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messagesBySession, dispatch] = useReducer(messagesReducer, {});
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);

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

  // Load sessions from backend on mount.
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    setSessionsLoading(true);

    fetchSessions()
      .then((apiSessions) => {
        const mapped: SessionMeta[] = apiSessions.map((s) => ({
          id: s.session_id,
          title: s.title || "Neuer Chat",
          updatedAt: new Date(s.last_activity || s.started_at),
          persisted: true,
        }));
        setSessions(mapped);
        clearLegacyStorage();
      })
      .catch(() => {
        // ignore — sessions stay empty on error
      })
      .finally(() => {
        setSessionsLoading(false);
        setSessionsLoaded(true);
      });
  }, []);

  const messages = activeSessionId
    ? messagesBySession[activeSessionId] ?? []
    : [];

  // ---------- Session actions ----------

  const createNewSession = useCallback(() => {
    const id = newId();
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

  const markStreamAborted = useCallback((sessionId: string) => {
    dispatch({
      type: "abort",
      sessionId,
      statusId: newId(),
      statusCreatedAt: Date.now(),
    });
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
        if (streamingSession) {
          markStreamAborted(streamingSession);
        }
      }
      setActiveSessionId(id);

      if (!messagesBySession[id]) {
        const session = sessions.find((s) => s.id === id);
        if (session?.persisted) {
          setMessagesLoading(true);
          fetchSessionMessages(id)
            .then((apiMessages) => {
              const mapped: Message[] = apiMessages.flatMap((m) => {
                const msgType = m.msg_type;
                let role: Message["role"];
                let toolStatus: Message["toolStatus"] | undefined;

                if (msgType) {
                  switch (msgType) {
                    case "user_text":
                    case "user_stt":
                      role = "user";
                      break;
                    case "llm_response":
                      role = "assistant";
                      break;
                    case "llm_thinking":
                      role = "thinking";
                      break;
                    case "ha_result":
                    case "tool_result":
                      role = "tool_call";
                      toolStatus = "done";
                      break;
                    default:
                      role = m.role === "user" ? "user" : "assistant";
                  }
                } else {
                  // Legacy messages without msg_type
                  role = m.role === "user" ? "user" : "assistant";
                }

                const msg: Message = {
                  id: newId(),
                  role,
                  content: m.content,
                  createdAt: new Date(m.timestamp).getTime(),
                  ...(toolStatus ? { toolStatus } : {}),
                };
                return [msg];
              });
              dispatch({ type: "reload", sessionId: id, messages: mapped });
            })
            .catch(() => {
              dispatch({ type: "reload", sessionId: id, messages: [] });
            })
            .finally(() => {
              setMessagesLoading(false);
            });
        }
      }
    },
    [messagesBySession, sessions, markStreamAborted]
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
          // keep optimistic update
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
      }

      const session = sessions.find((s) => s.id === id);

      setSessions((prev) => prev.filter((s) => s.id !== id));
      dispatch({ type: "delete_session", sessionId: id });

      if (session?.persisted) {
        deleteSessionApi(id).catch(() => {
          // already removed from UI
        });
      }

      if (activeSessionId === id) {
        const fresh = newId();
        const newSession: SessionMeta = {
          id: fresh,
          title: "Neuer Chat",
          updatedAt: new Date(),
          persisted: false,
        };
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(fresh);
      }
    },
    [activeSessionId, sessions]
  );

  // ---------- Message turn helpers ----------

  /**
   * Adds the user message and updates session metadata.
   * Returns the trimmed text plus the prior history (used by the legacy path).
   */
  const beginUserTurn = useCallback(
    (
      sessionId: string,
      text: string
    ): { trimmed: string; history: Message[] } => {
      const trimmed = text.trim();
      const history = messagesBySession[sessionId] ?? [];

      dispatch({
        type: "user_message",
        sessionId,
        id: newId(),
        content: trimmed,
        createdAt: Date.now(),
      });

      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const isFirstMessage =
            s.title === "Neuer Chat" && !history.some((m) => m.role === "user");
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

  // ---------- Streaming send (PROJ-30/31, redesigned in PROJ-35) ----------

  const streamingSend = useCallback(
    (sessionId: string, text: string, source?: string) => {
      const { trimmed } = beginUserTurn(sessionId, text);

      // Append an empty assistant placeholder; tokens will fill it in-place.
      dispatch({
        type: "assistant_placeholder",
        sessionId,
        id: newId(),
        createdAt: Date.now(),
      });

      streamingSessionRef.current = sessionId;
      isStreamingRef.current = true;
      setIsStreaming(true);

      // ---- SSE event handlers ----
      // Each handler dispatches exactly one reducer action; the reducer owns
      // all message-list mutations. Side effects that are NOT message state
      // (onTextResponse callback, ref/flag cleanup) stay here.

      let textResponseFired = false;
      const appendToken = (token: string) => {
        if (!textResponseFired) {
          textResponseFired = true;
          options.onTextResponse?.();
        }
        dispatch({
          type: "token",
          sessionId,
          token,
          id: newId(),
          createdAt: Date.now(),
        });
      };

      const appendThinking = (chunk: string) => {
        dispatch({
          type: "thinking",
          sessionId,
          chunk,
          id: newId(),
          createdAt: Date.now(),
        });
      };

      const handleToolStart = (tool: string, status?: string) => {
        dispatch({
          type: "tool_start",
          sessionId,
          id: newId(),
          createdAt: Date.now(),
          tool,
          status,
        });
      };

      const handleToolEnd = (tool: string, summary?: string) => {
        dispatch({ type: "tool_end", sessionId, tool, summary });
      };

      const finishStream = () => {
        streamingSessionRef.current = null;
        isStreamingRef.current = false;
        abortRef.current = null;
        setIsStreaming(false);
        dispatch({ type: "done", sessionId });
      };

      const handleError = (errMsg: string) => {
        dispatch({
          type: "error",
          sessionId,
          errMsg,
          id: newId(),
          createdAt: Date.now(),
        });
        streamingSessionRef.current = null;
        isStreamingRef.current = false;
        abortRef.current = null;
        setIsStreaming(false);
      };

      const handle = streamChat(
        sessionId,
        trimmed,
        {
          onToken: appendToken,
          onThinking: appendThinking,
          onToolStart: handleToolStart,
          onToolEnd: handleToolEnd,
          onVisionResults: options.onVisionResults,
          onDone: finishStream,
          onError: handleError,
        },
        source
      );

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

    if (sessionId) {
      markStreamAborted(sessionId);
    }
  }, [markStreamAborted]);

  // ---------- Legacy non-streaming send (fallback) ----------

  const legacySend = useCallback(
    async (sessionId: string, text: string) => {
      const { trimmed, history } = beginUserTurn(sessionId, text);

      setIsLoading(true);

      try {
        const allMessages: ChatMessage[] = [
          ...history
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({
              role: m.role as "user" | "assistant",
              content: m.content,
            })),
          { role: "user" as const, content: trimmed },
        ];

        const reply = await apiSendMessage(allMessages, sessionId);

        dispatch({
          type: "assistant_message",
          sessionId,
          id: newId(),
          content: reply,
          createdAt: Date.now(),
        });
      } catch (err) {
        dispatch({
          type: "error_message",
          sessionId,
          id: newId(),
          content:
            err instanceof Error ? err.message : i18n.t("chat.unknownError"),
          createdAt: Date.now(),
        });
      } finally {
        setIsLoading(false);
      }
    },
    [beginUserTurn]
  );

  const sendMessage = useCallback(
    async (text: string, source?: string) => {
      if (!activeSessionId || !text.trim()) return;
      if (isLoading || isStreaming) return;

      if (STREAM_API_URL) {
        streamingSend(activeSessionId, text, source);
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
    createNewSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
    stopStreaming,
  };
}
