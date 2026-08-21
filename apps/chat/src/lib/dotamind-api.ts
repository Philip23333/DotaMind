import type { ThreadMessage, ThreadMessageLike } from "@assistant-ui/react";

import { createUuidV4 } from "./uuid";
import { formatToolFailure, isToolFailureCode } from "./runtime-failure";

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
type ToolResultPayload = {
  data?: unknown;
};

export type CatalogEntity = {
  imagePath: string;
  label: string;
  names: string[];
};

export type RuntimeToolCallStatus = {
  tool_call_id: string;
  tool: string;
  status: "ok" | "error";
  latency_ms: number;
  reused: boolean;
  handler_entered: boolean;
  dispatch_stage: string;
  failure_code: string | null;
};

type RuntimeAttempt = {
  tool_call_statuses?: RuntimeToolCallStatus[];
};

export type PlanResponse = {
  status?: PlanStatus;
  reason?: string;
  error_code?: string | null;
  runtime?: { duration_ms?: number; attempts?: RuntimeAttempt[] };
  tool_results?: ToolResultPayload[];
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
      handler_entered?: boolean | null;
      dispatch_stage?: string | null;
    }
  | {
      type: "observer";
      kind: "model_prompt" | "model_output" | "tool_input" | "tool_output";
      stage: "controller" | "answer" | "tool";
      call_id: string;
      name: string;
      attempt_index: number;
      payload: Record<string, unknown>;
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
  if (typeof window === "undefined") return createUuidV4();
  const existing = window.localStorage.getItem(BROWSER_ID_STORAGE_KEY);
  if (existing) return existing;
  const created = createUuidV4();
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

export function clearStoredActiveSessionId(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function extractCatalogEntities(payload: PlanResponse): CatalogEntity[] {
  const entities: CatalogEntity[] = [];
  const seenImagePaths = new Set<string>();
  for (const toolResult of payload.tool_results ?? []) {
    const data = asRecord(toolResult.data);
    if (!data) continue;
    for (const key of ["hero", "item"]) {
      const entity = asRecord(data[key]);
      if (!entity) continue;
      const imagePath = entity.image_path;
      if (
        typeof imagePath !== "string" ||
        !imagePath.startsWith("/api/v1/assets/dota/") ||
        !imagePath.endsWith(".png")
      ) {
        continue;
      }
      const names = ["name_zh", "name_en", "name"]
        .map((field) => entity[field])
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean);
      if (!names.length || seenImagePaths.has(imagePath)) continue;
      seenImagePaths.add(imagePath);
      entities.push({
        imagePath,
        label: names[0] ?? (key === "hero" ? "英雄" : "物品"),
        names: Array.from(new Set(names)),
      });
    }
  }
  return entities;
}

export function decorateCatalogHeading(
  answerText: string | null | undefined,
  entities: CatalogEntity[],
): string | null {
  if (!answerText || !entities.length) return answerText ?? null;

  const lines = answerText.split("\n");
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const heading = lines[lineIndex].match(/^(#{1,6}\s+)(.*)$/);
    if (!heading) continue;
    const [, prefix, content] = heading;
    const matches = entities
      .map((entity) => {
        const name = entity.names.find((candidate) => content.includes(candidate));
        return name ? { entity, name } : null;
      })
      .filter((match): match is { entity: CatalogEntity; name: string } => match !== null)
      .sort((left, right) => right.name.length - left.name.length);
    const match = matches[0];
    if (!match) continue;
    const nameIndex = content.indexOf(match.name);
    const imageUrl = `${getApiUrl()}${match.entity.imagePath}`;
    if (content.includes(`](${imageUrl})`)) return answerText;
    lines[lineIndex] =
      `${prefix}${content.slice(0, nameIndex)}![${match.entity.label}](${imageUrl}) ` +
      content.slice(nameIndex);
    return lines.join("\n");
  }
  return answerText;
}

export function formatPlanResponse(payload: PlanResponse): string {
  const runtimeFailure = payload.runtime?.attempts
    ?.flatMap((attempt) => attempt.tool_call_statuses ?? [])
    .find((tool) => tool.status === "error" && tool.failure_code)?.failure_code;
  const reason = payload.reason?.trim();
  const shouldUseRuntimeFailure = Boolean(
    runtimeFailure &&
      !payload.answer?.summary?.trim() &&
      (!reason || ["tool execution failed", "execution failed"].includes(reason)),
  );
  const summaryOrReason = payload.answer?.summary?.trim() || payload.reason?.trim();
  const sections = [
    decorateCatalogHeading(
      summaryOrReason,
      payload.status === "ok" ? extractCatalogEntities(payload) : [],
    ),
    formatRecommendations(payload.answer?.recommendations),
    formatClaims(payload.answer?.claims),
    formatLimitations(payload.answer?.limitations),
  ].filter((section): section is string => Boolean(section));

  if (sections.length && !shouldUseRuntimeFailure) return sections.join("\n\n");

  if (shouldUseRuntimeFailure && isToolFailureCode(runtimeFailure)) {
    return formatToolFailure(runtimeFailure);
  }

  if (payload.error_code) {
    if (isToolFailureCode(payload.error_code)) return formatToolFailure(payload.error_code);
    return reason || `请求未能完成（${payload.error_code}），请稍后重试。`;
  }

  return "请求已完成，但服务没有返回可展示的回答。";
}

export function formatStreamError(errorCode: string, reason: string): string {
  const message = isToolFailureCode(errorCode)
    ? formatToolFailure(errorCode)
    : reason || "请求未能完成，请稍后重试。";
  return `${message}\n\n错误代码：\`${errorCode}\``;
}
