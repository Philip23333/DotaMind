import {
  ExportedMessageRepository,
  type ThreadHistoryAdapter,
  type ThreadMessageLike,
  useAuiState,
} from "@assistant-ui/react";
import { useMemo } from "react";

import {
  getChatSession,
  transcriptToInitialMessages,
} from "@/lib/dotamind-api";

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
  return useMemo<ThreadHistoryAdapter>(
    () => {
      return {
        async load() {
          if (!sessionId) {
            return { messages: [] };
          }

          const session = await getChatSession(browserId, sessionId);
          const messages = transcriptToInitialMessages(session);

          return {
            ...toRepository(messages),
          };
        },

        async append() {
          // The product endpoint persists user/final-assistant dialogue before completion.
        },
      };
    },
    [browserId, sessionId],
  );
}
