"use client";

import { useChatRunStore } from "@/contexts/chat-run-provider";

export function useChatRun(runId: string | null) {
  const store = useChatRunStore();
  return runId ? store.runsById[runId] ?? null : null;
}
