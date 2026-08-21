import type {
  ChatRunStatus,
  ChatRunSummary,
  PlanStreamEvent,
} from "./dotamind-api";
import { createUuidV4 } from "./uuid";

type ChatRunCreateResponse = { run: ChatRunSummary };
type ChatRunCancelResponse = { run: ChatRunSummary };
type ChatRunResumeResponse = { run: ChatRunSummary };
type ChatRunEventEnvelope = {
  run_id: string;
  session_id: string;
  sequence: number;
  event: PlanStreamEvent;
};
type ChatRunHeartbeat = {
  type: "heartbeat";
  run_id: string;
  session_id: string;
  status: ChatRunStatus;
  last_event_sequence: number;
};
type ChatRunStreamError = {
  type: "error";
  run_id: string;
  session_id: string;
  error_code: string;
};

export type ChatRunStreamItem = ChatRunEventEnvelope | ChatRunHeartbeat | ChatRunStreamError;

function apiUrl(): string {
  return (process.env.NEXT_PUBLIC_DOTAMIND_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

function headers(browserId: string, json = false): HeadersInit {
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    "X-DotaMind-Browser-Id": browserId,
  };
}

async function ensureOk(response: Response): Promise<void> {
  if (response.ok) return;
  let reason = `DotaMind API 请求失败（HTTP ${response.status}）。`;
  try {
    const payload = (await response.json()) as { reason?: string };
    reason = payload.reason?.trim() || reason;
  } catch {
    // Keep the status fallback for non-JSON errors.
  }
  throw new Error(reason);
}

export async function createChatRun(
  browserId: string,
  sessionId: string,
  query: string,
  requestId = createUuidV4(),
): Promise<ChatRunSummary> {
  const response = await fetch(`${apiUrl()}/api/v1/chat/sessions/${sessionId}/runs`, {
    method: "POST",
    headers: headers(browserId, true),
    body: JSON.stringify({ request_id: requestId, query, game: "dota2" }),
  });
  await ensureOk(response);
  return ((await response.json()) as ChatRunCreateResponse).run;
}

export async function getChatRun(
  browserId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<ChatRunSummary> {
  const response = await fetch(`${apiUrl()}/api/v1/chat/runs/${runId}`, {
    headers: headers(browserId),
    signal,
  });
  await ensureOk(response);
  return (await response.json()) as ChatRunSummary;
}

export async function getActiveChatRun(
  browserId: string,
  sessionId: string,
): Promise<ChatRunSummary | null> {
  const response = await fetch(`${apiUrl()}/api/v1/chat/sessions/${sessionId}/active-run`, {
    headers: headers(browserId),
  });
  await ensureOk(response);
  return (await response.json()) as ChatRunSummary | null;
}

export async function cancelChatRun(
  browserId: string,
  runId: string,
): Promise<ChatRunSummary> {
  const response = await fetch(`${apiUrl()}/api/v1/chat/runs/${runId}/cancel`, {
    method: "POST",
    headers: headers(browserId),
  });
  await ensureOk(response);
  return ((await response.json()) as ChatRunCancelResponse).run;
}

export async function resumeChatRun(
  browserId: string,
  runId: string,
  checkpointType: string,
  optionId: string,
): Promise<ChatRunSummary> {
  const response = await fetch(`${apiUrl()}/api/v1/chat/runs/${runId}/resume`, {
    method: "POST",
    headers: headers(browserId, true),
    body: JSON.stringify({ checkpoint_type: checkpointType, option_id: optionId }),
  });
  await ensureOk(response);
  return ((await response.json()) as ChatRunResumeResponse).run;
}

export async function* subscribeChatRun(
  browserId: string,
  runId: string,
  after = 0,
  signal?: AbortSignal,
): AsyncGenerator<ChatRunStreamItem> {
  const response = await fetch(
    `${apiUrl()}/api/v1/chat/runs/${runId}/events?after=${after}`,
    { headers: headers(browserId), signal },
  );
  await ensureOk(response);
  if (!response.body) throw new Error("DotaMind API 未返回可读取的事件流。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as ChatRunStreamItem;
    }
    if (done) break;
  }
  if (buffer.trim()) yield JSON.parse(buffer) as ChatRunStreamItem;
}
