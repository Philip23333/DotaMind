"use client";

import { useEffect, useState } from "react";

import { useChatRunStore } from "@/contexts/chat-run-provider";
import { getChatSession, type ChatSessionResponse } from "@/lib/dotamind-api";

export function useSessionLoader(browserId: string | null, sessionId: string | null) {
  const { registerRun } = useChatRunStore();
  const [session, setSession] = useState<ChatSessionResponse | null>(null);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!browserId || !sessionId) return;
    const controller = new AbortController();
    Promise.resolve().then(() => {
      if (!controller.signal.aborted) {
        setLoading(true);
        setError(null);
      }
    });
    getChatSession(browserId, sessionId)
      .then((next) => {
        if (next.session.active_run) registerRun(next.session.active_run);
        setSession(next);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason : new Error(String(reason)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [browserId, sessionId, registerRun]);

  return { session, loading, error };
}
