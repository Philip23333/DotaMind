import {
  type ChatModelAdapter,
  useAui,
} from "@assistant-ui/react";
import { useMemo } from "react";

import { latestUserText } from "@/lib/dotamind-api";
import { streamVNextChatMessage } from "./vnext-event-converter";

export function useDotaMindModelAdapter(browserId: string): ChatModelAdapter {
  const aui = useAui();

  return useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal }) {
        const query = latestUserText(messages);
        if (!query) throw new Error("请输入问题后再发送。");

        const { remoteId: sessionId } = await aui.threadListItem.initialize();
        yield* streamVNextChatMessage({
          browserId,
          sessionId,
          query,
          abortSignal,
        });
      },
    }),
    [aui, browserId],
  );
}
