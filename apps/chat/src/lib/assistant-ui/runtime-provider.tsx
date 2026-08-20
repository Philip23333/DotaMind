"use client";

import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
} from "@assistant-ui/react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { useDotaMindHistoryAdapter } from "./dotamind-history-adapter";
import { useDotaMindModelAdapter } from "./dotamind-model-adapter";
import { createDotaMindThreadListAdapter } from "./dotamind-thread-list-adapter";

export function useDotaMindThreadRuntime(browserId: string) {
  const modelAdapter = useDotaMindModelAdapter(browserId);
  const historyAdapter = useDotaMindHistoryAdapter(browserId);
  return useLocalRuntime(modelAdapter, {
    adapters: { history: historyAdapter },
  });
}

export function DotaMindRuntimeProvider({
  browserId,
  children,
}: {
  browserId: string;
  children: ReactNode;
}) {
  const adapter = useMemo(() => createDotaMindThreadListAdapter(browserId), [browserId]);
  const [threadId, setThreadId] = useState<string | undefined>();
  const runtimeHook = useCallback(
    function useDotaMindThreadRuntimeHook() {
      return useDotaMindThreadRuntime(browserId);
    },
    [browserId],
  );
  const onThreadIdChange = useCallback((nextThreadId: string | undefined) => {
    setThreadId(nextThreadId);
  }, []);
  const runtime = useRemoteThreadListRuntime({
    runtimeHook,
    adapter,
    threadId,
    onThreadIdChange,
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}
