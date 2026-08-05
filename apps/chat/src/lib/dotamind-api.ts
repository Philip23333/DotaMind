import type { ThreadMessage, ThreadMessageLike } from "@assistant-ui/react";

const DEFAULT_API_URL = "http://localhost:8001";
export const BROWSER_ID_STORAGE_KEY = "dotamind.browser_id.v1";
export const ACTIVE_SESSION_STORAGE_KEY = "dotamind.active_session_id.v1";

export type PlanStatus =
  | "ok"
  | "clarification_required"
  | "insufficient_context"
  | "insufficient_tools"
  | "insufficient_evidence"
  | "error";

type AnswerItem = Record<string, unknown>;

export type PlanResponse = {
  status?: PlanStatus;
  reason?: string;
  error_code?: string | null;
  runtime?: { duration_ms?: number };
  answer?: {
    summary?: string;
    claims?: AnswerItem[];
    recommendations?: AnswerItem[];
    limitations?: AnswerItem[];
  } | null;
};

export type ChatSessionSummary = {
  session_id: string;
  game: "dota2";
  title: string;
  title_is_custom: boolean;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
  active_run?: ChatRunSummary | null;
};

export type ChatRunStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export type ChatRunSummary = {
  run_id: string;
  session_id: string;
  request_id: string;
  status: ChatRunStatus;
  user_query: string;
  last_event_sequence: number;
  result_turn_id: string | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  heartbeat_at: string | null;
  cancel_requested_at: string | null;
  completed_at: string | null;
};

export type ChatTranscriptTurn = {
  turn_index: number;
  request_id: string;
  user_query: string;
  public_response: PlanResponse;
  created_at: string;
};

export type ChatSessionResponse = {
  session: ChatSessionSummary;
  turns: ChatTranscriptTurn[];
};

export type PlanStreamEvent =
  | {
      type: "phase";
      phase: "planning" | "tool_execution" | "answering" | "reviewing";
      attempt_index: number;
    }
  | {
      type: "tool";
      tool_call_id: string;
      tool: string;
      attempt_index: number;
      status: "running" | "ok" | "error";
      latency_ms: number | null;
      reused: boolean | null;
      failure_code: string | null;
    }
  | { type: "answer_delta"; delta: string; attempt_index: number; provisional: true }
  | { type: "result"; response: PlanResponse; session?: ChatSessionSummary | null }
  | { type: "error"; error_code: string; reason: string }
  | {
      type: "status";
      status: ChatRunStatus;
      error_code?: string | null;
      transcript_recovery?: boolean;
    };

export function getApiUrl(): string {
  return (process.env.NEXT_PUBLIC_DOTAMIND_API_URL ?? DEFAULT_API_URL).replace(
    /\/$/,
    "",
  );
}

export function getOrCreateBrowserId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const existing = window.localStorage.getItem(BROWSER_ID_STORAGE_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(BROWSER_ID_STORAGE_KEY, created);
  return created;
}

export function getStoredActiveSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
}

export function storeActiveSessionId(sessionId: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  }
}

function browserHeaders(browserId: string, includeJson = false): HeadersInit {
  return {
    ...(includeJson ? { "Content-Type": "application/json" } : {}),
    "X-DotaMind-Browser-Id": browserId,
  };
}

async function readResponseError(response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { reason?: string };
    return new Error(payload.reason?.trim() || `DotaMind API 请求失败（HTTP ${response.status}）。`);
  } catch {
    return new Error(`DotaMind API 请求失败（HTTP ${response.status}）。`);
  }
}

export async function listChatSessions(browserId: string): Promise<ChatSessionSummary[]> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions`, {
    headers: browserHeaders(browserId),
  });
  if (!response.ok) throw await readResponseError(response);
  const payload = (await response.json()) as { sessions: ChatSessionSummary[] };
  return payload.sessions;
}

export async function createChatSession(browserId: string): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions`, {
    method: "POST",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ game: "dota2" }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function getChatSession(
  browserId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ChatSessionResponse> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    headers: browserHeaders(browserId),
    signal,
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionResponse;
}

export async function renameChatSession(
  browserId: string,
  sessionId: string,
  title: string,
): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ title }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function setChatSessionPinned(
  browserId: string,
  sessionId: string,
  isPinned: boolean,
): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ is_pinned: isPinned }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function deleteChatSession(browserId: string, sessionId: string): Promise<void> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: browserHeaders(browserId),
  });
  if (!response.ok) throw await readResponseError(response);
}

export function transcriptToInitialMessages(
  session: ChatSessionResponse,
): ThreadMessageLike[] {
  return session.turns.flatMap((turn) => [
    {
      id: `${session.session.session_id}:user:${turn.turn_index}`,
      role: "user" as const,
      content: [{ type: "text" as const, text: turn.user_query }],
      createdAt: new Date(turn.created_at),
    },
    {
      id: `${session.session.session_id}:assistant:${turn.turn_index}`,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: formatPlanResponse(turn.public_response) }],
      status: { type: "complete" as const, reason: "stop" as const },
      createdAt: new Date(turn.created_at),
    },
  ]);
}

export function pendingRunToInitialMessages(run: ChatRunSummary): ThreadMessageLike[] {
  return [
    {
      id: `${run.run_id}:user`,
      role: "user" as const,
      content: [{ type: "text" as const, text: run.user_query }],
    },
    {
      id: `${run.run_id}:assistant`,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "正在恢复分析运行…" }],
    },
  ];
}

export function latestUserText(messages: readonly ThreadMessage[]): string {
  const message = messages.findLast((item) => item.role === "user");

  return (
    message?.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n")
      .trim() ?? ""
  );
}

function stringField(item: AnswerItem, key: string): string | null {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function formatRecommendations(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items.flatMap((item) => {
    const subject = stringField(item, "subject");
    const rationale = stringField(item, "rationale");
    if (!subject && !rationale) return [];
    if (subject && rationale) return [`- **${subject}**：${rationale}`];
    return [`- ${subject ?? rationale}`];
  });

  return lines.length ? `### 建议\n\n${lines.join("\n")}` : null;
}

function formatClaims(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items
    .map((item) => stringField(item, "claim"))
    .filter((claim): claim is string => claim !== null)
    .map((claim) => `- ${claim}`);

  return lines.length ? `### 依据\n\n${lines.join("\n")}` : null;
}

function formatLimitations(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items
    .map((item) => stringField(item, "detail"))
    .filter((detail): detail is string => detail !== null)
    .map((detail) => `- ${detail}`);

  return lines.length ? `### 注意\n\n${lines.join("\n")}` : null;
}

export function formatPlanResponse(payload: PlanResponse): string {
  const sections = [
    payload.answer?.summary?.trim() || payload.reason?.trim(),
    formatRecommendations(payload.answer?.recommendations),
    formatClaims(payload.answer?.claims),
    formatLimitations(payload.answer?.limitations),
  ].filter((section): section is string => Boolean(section));

  if (sections.length) return sections.join("\n\n");

  if (payload.error_code) {
    return `请求未能完成（${payload.error_code}），请稍后重试。`;
  }

  return "请求已完成，但服务没有返回可展示的回答。";
}

export function formatStreamError(errorCode: string, reason: string): string {
  return `${reason || "请求未能完成，请稍后重试。"}\n\n错误代码：\`${errorCode}\``;
}

function parseEvent(line: string): PlanStreamEvent {
  const parsed: unknown = JSON.parse(line);
  if (!parsed || typeof parsed !== "object" || !("type" in parsed)) {
    throw new Error("DotaMind API 返回了无效的流事件。");
  }
  return parsed as PlanStreamEvent;
}

export async function* streamDotaMind(
  query: string,
  sessionId: string,
  browserId: string,
  abortSignal: AbortSignal,
): AsyncGenerator<PlanStreamEvent> {
  const response = await fetch(`${getApiUrl()}/api/v1/plan/stream`, {
    method: "POST",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({
      query,
      game: "dota2",
      session_id: sessionId,
      request_id: crypto.randomUUID(),
    }),
    signal: abortSignal,
  });

  if (!response.ok) {
    let reason = `DotaMind API 请求失败（HTTP ${response.status}）。`;
    try {
      const payload = (await response.json()) as PlanResponse;
      reason = payload.reason?.trim() || reason;
    } catch {
      // Preserve the safe HTTP-status fallback for non-JSON validation responses.
    }
    throw new Error(reason);
  }

  if (!response.body) {
    throw new Error("DotaMind API 未返回可读取的流响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.trim()) yield parseEvent(line.trim());
    }

    if (done) break;
  }

  if (buffer.trim()) yield parseEvent(buffer.trim());
}
