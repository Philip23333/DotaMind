"use client";

import {
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import { Thread } from "@/components/thread";
import { askDotaMind, latestUserText } from "@/lib/dotamind-api";
import { useMemo, useState } from "react";

export const Assistant = () => {
  const [sessionId] = useState(() => crypto.randomUUID());
  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        const query = latestUserText(messages);
        if (!query) {
          throw new Error("请输入问题后再发送。");
        }

        const text = await askDotaMind(query, sessionId, abortSignal);
        return { content: [{ type: "text", text }] };
      },
    }),
    [sessionId],
  );
  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-dvh flex-col bg-background">
        <header className="flex h-14 shrink-0 items-center border-b px-4 sm:px-6">
          <div>
            <div className="text-sm font-semibold tracking-tight">DotaMind</div>
            <div className="text-xs text-muted-foreground">
              Dota 2 智能分析助手
            </div>
          </div>
        </header>
        <div className="min-h-0 flex-1">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
};
