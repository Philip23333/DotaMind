import {
  type ChatModelAdapter,
  useAuiState,
} from "@assistant-ui/react";
import { useMemo } from "react";

import { createChatRun } from "@/lib/chat-run-api";
import { latestUserText } from "@/lib/dotamind-api";
import { streamDotaMindRun } from "./run-event-converter";

export function useDotaMindModelAdapter(browserId: string): ChatModelAdapter {
  const sessionId = useAuiState((state) => state.threadListItem.remoteId);

  return useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_assistantMessageId, unstable_threadId }) {
        const query = latestUserText(messages);
        if (!query) throw new Error("请输入问题后再发送。");

        const resolvedSessionId = unstable_threadId ?? sessionId;
        if (!resolvedSessionId) {
          throw new Error("聊天会话尚未初始化，请重试。");
        }

        const run = await createChatRun(browserId, resolvedSessionId, query);
        yield* streamDotaMindRun({
          browserId,
          runId: run.run_id,
          sessionId: resolvedSessionId,
          requestId: run.request_id,
          messageId: unstable_assistantMessageId ?? `${run.run_id}:assistant`,
          abortSignal,
        });
      },
    }),
    [browserId, sessionId],
  );
}
