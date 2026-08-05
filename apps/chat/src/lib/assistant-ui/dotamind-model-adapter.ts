import {
  type ChatModelAdapter,
  useAui,
} from "@assistant-ui/react";
import { useMemo } from "react";

import { createChatRun } from "@/lib/chat-run-api";
import { latestUserText } from "@/lib/dotamind-api";
import { streamDotaMindRun } from "./run-event-converter";
import { createRunForInitializedThread } from "./thread-initialization";

export function useDotaMindModelAdapter(browserId: string): ChatModelAdapter {
  const aui = useAui();

  return useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_assistantMessageId }) {
        const query = latestUserText(messages);
        if (!query) throw new Error("请输入问题后再发送。");

        const { run, sessionId } = await createRunForInitializedThread({
          browserId,
          query,
          initializeThread: () => aui.threadListItem.initialize(),
          createRun: createChatRun,
        });
        yield* streamDotaMindRun({
          browserId,
          runId: run.run_id,
          sessionId,
          requestId: run.request_id,
          messageId: unstable_assistantMessageId ?? `${run.run_id}:assistant`,
          abortSignal,
        });
      },
    }),
    [aui, browserId],
  );
}
