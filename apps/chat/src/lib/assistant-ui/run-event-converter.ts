import type { ChatModelRunResult } from "@assistant-ui/react";

import {
  formatPlanResponse,
  formatStreamError,
  getChatSession,
  type ChatRunStatus,
  type PlanStreamEvent,
  type PlanResponse,
} from "@/lib/dotamind-api";
import {
  subscribeChatRun,
  type ChatRunStreamItem,
} from "@/lib/chat-run-api";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "./migration-contract";
import { markDotaMindSessionUnread } from "./thread-unread";

export type DotaMindRuntimeTool = Extract<PlanStreamEvent, { type: "tool" }>;
export type DotaMindObservation = Extract<PlanStreamEvent, { type: "observer" }>;

export type DotaMindRuntimeInfo = {
  messageId: string;
  phase: Extract<PlanStreamEvent, { type: "phase" }>["phase"];
  tools: DotaMindRuntimeTool[];
  observations: DotaMindObservation[];
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

function updateObservation(
  observations: DotaMindObservation[],
  incoming: DotaMindObservation,
) {
  const index = observations.findIndex(
    (item) =>
      item.attempt_index === incoming.attempt_index &&
      item.stage === incoming.stage &&
      item.call_id === incoming.call_id &&
      item.kind === incoming.kind,
  );
  if (index === -1) return [...observations, incoming];
  return observations.map((item, itemIndex) =>
    itemIndex === index ? incoming : item,
  );
}

function responseTools(response: PlanResponse): DotaMindRuntimeTool[] {
  return (response.runtime?.attempts ?? []).flatMap((attempt, attemptIndex) =>
    (attempt.tool_call_statuses ?? []).map((tool) => ({
      type: "tool" as const,
      tool_call_id: tool.tool_call_id,
      tool: tool.tool,
      attempt_index: attemptIndex,
      status: tool.status,
      latency_ms: tool.latency_ms,
      reused: tool.reused,
      failure_code: tool.failure_code,
      handler_entered: tool.handler_entered,
      dispatch_stage: tool.dispatch_stage,
    })),
  );
}

function mergeResponseTools(
  tools: DotaMindRuntimeTool[],
  response: PlanResponse,
): DotaMindRuntimeTool[] {
  return responseTools(response).reduce(updateTool, tools);
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
  let markedUnread = false;
  let runtime: DotaMindRuntimeInfo = {
    messageId: options.messageId,
    phase: "planning",
    tools: [],
    observations: [],
    status: "running",
  };

  const update = (result: Omit<ChatModelRunResult, "metadata"> = {}) => ({
    ...result,
    metadata: metadata(options.runId, runtime),
  });

  const markUnread = () => {
    if (markedUnread) return;
    markedUnread = true;
    markDotaMindSessionUnread(options.sessionId);
  };

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
        if (receivedTerminalEvent) markUnread();
        yield update();
        if (receivedTerminalEvent) return;
        continue;
      }

      runtime = { ...runtime, status: "failed" };
      receivedTerminalEvent = true;
      markUnread();
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
      case "observer":
        runtime = {
          ...runtime,
          observations: updateObservation(runtime.observations, event),
        };
        yield update();
        break;
      case "answer_delta":
        provisionalText += event.delta;
        yield update({ content: [{ type: "text", text: provisionalText }] });
        break;
      case "result":
        runtime = {
          ...runtime,
          tools: mergeResponseTools(runtime.tools, event.response),
          status: event.response.status === "error" || event.response.status === "insufficient_evidence"
            ? "failed"
            : "completed",
          durationMs: event.response.runtime?.duration_ms,
        };
        receivedTerminalEvent = true;
        markUnread();
        yield update({ content: [{ type: "text", text: formatPlanResponse(event.response) }] });
        return;
      case "error":
        runtime = { ...runtime, status: "failed" };
        receivedTerminalEvent = true;
        markUnread();
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
        markUnread();
        if (event.status === "completed") {
          const response = await recoveredResponse(
            options.browserId,
            options.sessionId,
            options.requestId,
            options.abortSignal,
          ).catch(() => undefined);
          if (response) runtime = { ...runtime, tools: mergeResponseTools(runtime.tools, response) };
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
