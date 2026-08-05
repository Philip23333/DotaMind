import {
  ExportedMessageRepository,
  type ChatModelRunOptions,
  type ThreadHistoryAdapter,
  type ThreadMessageLike,
  useAuiState,
} from "@assistant-ui/react";
import { useMemo, useRef } from "react";

import {
  getChatSession,
  pendingRunToInitialMessages,
  transcriptToInitialMessages,
  type ChatRunSummary,
} from "@/lib/dotamind-api";
import { streamDotaMindRun } from "./run-event-converter";

function toRepository(messages: ThreadMessageLike[]) {
  let parentId: string | null = null;
  const items = messages.map((message) => {
    const item = { parentId, message };
    parentId = message.id ?? null;
    return item;
  });
  return ExportedMessageRepository.fromBranchableArray(items, { headId: parentId });
}

export function useDotaMindHistoryAdapter(browserId: string): ThreadHistoryAdapter {
  const sessionId = useAuiState((state) => state.threadListItem.remoteId);
  const recoveredRunRef = useRef<ChatRunSummary | null>(null);

  return useMemo<ThreadHistoryAdapter>(
    () => {
      return {
        async load() {
          if (!sessionId) {
            recoveredRunRef.current = null;
            return { messages: [] };
          }

          const session = await getChatSession(browserId, sessionId);
          recoveredRunRef.current = session.session.active_run ?? null;
          const messages = transcriptToInitialMessages(session);
          if (recoveredRunRef.current) {
            messages.push(...pendingRunToInitialMessages(recoveredRunRef.current).slice(0, 1));
          }

          return {
            ...toRepository(messages),
            unstable_resume: Boolean(recoveredRunRef.current),
          };
        },

        async *resume(options: ChatModelRunOptions) {
          const run = recoveredRunRef.current;
          if (!run || !sessionId) return;

          yield* streamDotaMindRun({
            browserId,
            runId: run.run_id,
            sessionId,
            requestId: run.request_id,
            messageId: options.unstable_assistantMessageId ?? `${run.run_id}:assistant`,
            after: 0,
            abortSignal: options.abortSignal,
          });
        },

        async append() {
          // DotaMind persists user/assistant turns in the Run transaction.
        },
      };
    },
    [browserId, recoveredRunRef, sessionId],
  );
}
