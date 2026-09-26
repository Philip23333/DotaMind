"use client";

import {
  AssistantRuntimeProvider,
  useRemoteThreadListRuntime,
} from "@assistant-ui/react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import {
  DotaMindThreadStateProvider,
  useDotaMindTransportThreadRuntime,
} from "./dotamind-transport-runtime";
import { DotaMindThreadStateRegistry } from "./dotamind-thread-state";
import { createDotaMindThreadListAdapter } from "./dotamind-thread-list-adapter";

export function DotaMindRuntimeProvider({
  browserId,
  children,
}: {
  browserId: string;
  children: ReactNode;
}) {
  const adapter = useMemo(() => createDotaMindThreadListAdapter(browserId), [browserId]);
  const threadStates = useMemo(() => new DotaMindThreadStateRegistry(browserId), [browserId]);
  const [threadId, setThreadId] = useState<string | undefined>();
  const runtimeHook = useCallback(
    function useDotaMindThreadRuntimeHook() {
      return useDotaMindTransportThreadRuntime(browserId, threadStates);
    },
    [browserId, threadStates],
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

  return (
    <DotaMindThreadStateProvider registry={threadStates}>
      <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
    </DotaMindThreadStateProvider>
  );
}
