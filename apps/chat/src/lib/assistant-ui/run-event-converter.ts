import type { ChatModelRunResult } from "@assistant-ui/react";

import {
  formatPlanResponse,
  formatStreamError,
  getChatSession,
  type ChatRunStatus,
  type PlanStreamEvent,
} from "@/lib/dotamind-api";
import {
  subscribeChatRun,
  type ChatRunStreamItem,
} from "@/lib/chat-run-api";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "./migration-contract";

export type DotaMindRuntimeTool = Extract<PlanStreamEvent, { type: "tool" }>;

export type DotaMindRuntimeInfo = {
  messageId: string;
  phase: Extract<PlanStreamEvent, { type: "phase" }>["phase"];
  tools: DotaMindRuntimeTool[];
  status: "running" | "completed" | "failed" | "cancelled";
  durationMs?: number;
};

type StreamChatRunOptions = {
  browserId: string;
  runId: string;
  sessionId: string;
  requestId: string;
  messageId: string;
  after?: number;
  abortSignal: AbortSignal;
};

function terminalStatus(status: ChatRunStatus): DotaMindRuntimeInfo["status"] {
  if (status === "cancelled") return "cancelled";
  if (status === "completed") return "completed";
  return "failed";
}

function metadata(runId: string, runtime: DotaMindRuntimeInfo): ChatModelRunResult["metadata"] {
  return {
    custom: {
      [DOTAMIND_ASSISTANT_METADATA_KEY]: {
        runId,
        runtime,
      },
    },
  };
}

function updateTool(tools: DotaMindRuntimeTool[], incoming: DotaMindRuntimeTool) {
  const index = tools.findIndex((tool) => tool.tool_call_id === incoming.tool_call_id);
  if (index === -1) return [...tools, incoming];
  return tools.map((tool, toolIndex) => (toolIndex === index ? incoming : tool));
}

async function recoveredResponse(
  browserId: string,
  sessionId: string,
  requestId: string,
  signal: AbortSignal,
) {
  const session = await getChatSession(browserId, sessionId, signal);
  return session.turns.find((turn) => turn.request_id === requestId)?.public_response;
}

export async function* streamDotaMindRun(
  options: StreamChatRunOptions,
): AsyncGenerator<ChatModelRunResult, void> {
  let provisionalText = "";
  let receivedTerminalEvent = false;
  let runtime: DotaMindRuntimeInfo = {
    messageId: options.messageId,
    phase: "planning",
    tools: [],
    status: "running",
  };

  const update = (result: Omit<ChatModelRunResult, "metadata"> = {}) => ({
    ...result,
    metadata: metadata(options.runId, runtime),
  });

  for await (const item of subscribeChatRun(
    options.browserId,
    options.runId,
    options.after ?? 0,
    options.abortSignal,
  )) {
    if (options.abortSignal.aborted) return;

    if (!("sequence" in item)) {
      if (item.type === "heartbeat") {
        runtime = {
          ...runtime,
          status: ["queued", "running", "cancel_requested"].includes(item.status)
            ? "running"
            : terminalStatus(item.status),
        };
        if (runtime.status !== "running") receivedTerminalEvent = true;
        yield update();
        if (receivedTerminalEvent) return;
        continue;
      }

      runtime = { ...runtime, status: "failed" };
      receivedTerminalEvent = true;
      yield update({
        content: [{ type: "text", text: formatStreamError(item.error_code, "Run 事件订阅失败。") }],
      });
      return;
    }

    const event = item.event;
    switch (event.type) {
      case "phase":
        runtime = { ...runtime, phase: event.phase };
        yield update();
        break;
      case "tool":
        runtime = { ...runtime, tools: updateTool(runtime.tools, event) };
        yield update();
        break;
      case "answer_delta":
        provisionalText += event.delta;
        yield update({ content: [{ type: "text", text: provisionalText }] });
        break;
      case "result":
        runtime = {
          ...runtime,
          status: event.response.status === "error" || event.response.status === "insufficient_evidence"
            ? "failed"
            : "completed",
          durationMs: event.response.runtime?.duration_ms,
        };
        receivedTerminalEvent = true;
        yield update({ content: [{ type: "text", text: formatPlanResponse(event.response) }] });
        return;
      case "error":
        runtime = { ...runtime, status: "failed" };
        receivedTerminalEvent = true;
        yield update({ content: [{ type: "text", text: formatStreamError(event.error_code, event.reason) }] });
        return;
      case "status": {
        runtime = {
          ...runtime,
          status: ["queued", "running", "cancel_requested"].includes(event.status)
            ? "running"
            : terminalStatus(event.status),
        };
        if (["queued", "running", "cancel_requested"].includes(event.status)) {
          yield update();
          break;
        }

        receivedTerminalEvent = true;
        if (event.status === "completed") {
          const response = await recoveredResponse(
            options.browserId,
            options.sessionId,
            options.requestId,
            options.abortSignal,
          ).catch(() => undefined);
          yield update({
            content: [
              {
                type: "text",
                text: response ? formatPlanResponse(response) : provisionalText || incompleteMessage,
              },
            ],
          });
        } else if (event.status === "cancelled") {
          yield update({ content: [{ type: "text", text: cancelledMessage }] });
        } else {
          yield update({
            content: [{ type: "text", text: formatStreamError(event.error_code ?? event.status, "Run 未能完成。") }],
          });
        }
        return;
      }
    }
  }

  if (!receivedTerminalEvent && !options.abortSignal.aborted) {
    runtime = { ...runtime, status: "failed" };
    yield update({ content: [{ type: "text", text: incompleteMessage }] });
  }
}

const cancelledMessage = "本次分析已取消。";
const incompleteMessage = "连接在收到最终结果前结束，请重试。";

export function getRunStreamItemIdentity(item: ChatRunStreamItem): string {
  return `${item.run_id}:${item.session_id}`;
}
