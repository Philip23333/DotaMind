"use client";

import { createContext, useCallback, useContext, useMemo, useReducer, type ReactNode } from "react";

import type { ChatRunSummary } from "@/lib/dotamind-api";
import type { ChatRunStreamItem } from "@/lib/chat-run-api";
import { chatRunReducer, EMPTY_CHAT_RUN_STORE, type ChatRunStoreState } from "@/lib/chat-run-store";

type ChatRunContextValue = ChatRunStoreState & {
  registerRun: (summary: ChatRunSummary) => void;
  applyEvent: (item: ChatRunStreamItem) => void;
  removeRun: (runId: string) => void;
  clearSessionRuns: (sessionId: string) => void;
};

const ChatRunContext = createContext<ChatRunContextValue | null>(null);

export function ChatRunProvider({ children }: { children: ReactNode }) {
  const [store, dispatch] = useReducer(chatRunReducer, EMPTY_CHAT_RUN_STORE);
  const registerRun = useCallback((summary: ChatRunSummary) => dispatch({ type: "register", summary }), []);
  const applyEvent = useCallback((item: ChatRunStreamItem) => dispatch({ type: "event", item }), []);
  const removeRun = useCallback((runId: string) => dispatch({ type: "remove", runId }), []);
  const clearSessionRuns = useCallback((sessionId: string) => dispatch({ type: "clear_session", sessionId }), []);
  const value = useMemo(
    () => ({ ...store, registerRun, applyEvent, removeRun, clearSessionRuns }),
    [store, registerRun, applyEvent, removeRun, clearSessionRuns],
  );
  return <ChatRunContext.Provider value={value}>{children}</ChatRunContext.Provider>;
}

export function useChatRunStore(): ChatRunContextValue {
  const context = useContext(ChatRunContext);
  if (!context) throw new Error("useChatRunStore must be used inside ChatRunProvider");
  return context;
}
