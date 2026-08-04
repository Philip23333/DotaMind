"use client";

import {
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import {
  RuntimeInfoProvider,
  type RuntimeInfo,
  type RuntimeInfoMap,
  type RuntimeTool,
} from "@/components/runtime-info";
import { Thread } from "@/components/thread";
import {
  formatPlanResponse,
  formatStreamError,
  latestUserText,
  streamDotaMind,
} from "@/lib/dotamind-api";
import { useCallback, useMemo, useState } from "react";

const finalRunStatus = (status: string | undefined): RuntimeInfo["status"] =>
  status === "error" || status === "insufficient_evidence" ? "failed" : "completed";

const cancelledMessage = "本次分析已取消。";
const incompleteMessage = "连接在收到最终结果前结束，请重试。";

export const Assistant = () => {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [runtimeRuns, setRuntimeRuns] = useState<RuntimeInfoMap>({});
  const updateRuntimeRun = useCallback(
    (messageId: string, updater: (run: RuntimeInfo) => RuntimeInfo) => {
      setRuntimeRuns((runs) => {
        const run = runs[messageId];
        return run ? { ...runs, [messageId]: updater(run) } : runs;
      });
    },
    [],
  );
  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_assistantMessageId }) {
        const query = latestUserText(messages);
        if (!query) {
          throw new Error("请输入问题后再发送。");
        }

        const messageId = unstable_assistantMessageId ?? crypto.randomUUID();
        setRuntimeRuns((runs) => ({
          ...runs,
          [messageId]: {
            messageId,
            phase: "planning",
            tools: [],
            status: "running",
          },
        }));
        let provisionalText = "";
        let receivedTerminalEvent = false;

        try {
          for await (const event of streamDotaMind(query, sessionId, abortSignal)) {
            switch (event.type) {
              case "phase":
                updateRuntimeRun(messageId, (run) => ({ ...run, phase: event.phase }));
                break;
              case "tool":
                updateRuntimeRun(messageId, (run) => ({
                  ...run,
                  tools: upsertTool(run.tools, event),
                }));
                break;
              case "answer_delta":
                provisionalText += event.delta;
                yield { content: [{ type: "text", text: provisionalText }] };
                break;
              case "result":
                receivedTerminalEvent = true;
                updateRuntimeRun(messageId, (run) => ({
                  ...run,
                  status: finalRunStatus(event.response.status),
                  durationMs: event.response.runtime?.duration_ms,
                }));
                yield { content: [{ type: "text", text: formatPlanResponse(event.response) }] };
                return;
              case "error":
                receivedTerminalEvent = true;
                updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
                yield {
                  content: [{ type: "text", text: formatStreamError(event.error_code, event.reason) }],
                };
                return;
            }
          }

          if (!receivedTerminalEvent) {
            updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
            yield { content: [{ type: "text", text: incompleteMessage }] };
          }
        } catch (error) {
          if (error instanceof Error && error.name === "AbortError") {
            updateRuntimeRun(messageId, (run) => ({ ...run, status: "cancelled" }));
            yield { content: [{ type: "text", text: cancelledMessage }] };
            return;
          }

          updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
          throw error;
        }
      },
    }),
    [sessionId, updateRuntimeRun],
  );
  const runtime = useLocalRuntime(adapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <RuntimeInfoProvider value={runtimeRuns}>
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
      </RuntimeInfoProvider>
    </AssistantRuntimeProvider>
  );
};

const upsertTool = (tools: RuntimeTool[], incoming: RuntimeTool): RuntimeTool[] => {
  const index = tools.findIndex((tool) => tool.tool_call_id === incoming.tool_call_id);
  if (index === -1) return [...tools, incoming];

  return tools.map((tool, toolIndex) => (toolIndex === index ? incoming : tool));
};
