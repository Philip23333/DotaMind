import type { ThreadMessage } from "@assistant-ui/react";

const DEFAULT_API_URL = "http://localhost:8001";

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
  | { type: "result"; response: PlanResponse }
  | { type: "error"; error_code: string; reason: string };

export function getApiUrl(): string {
  return (process.env.NEXT_PUBLIC_DOTAMIND_API_URL ?? DEFAULT_API_URL).replace(
    /\/$/,
    "",
  );
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
  abortSignal: AbortSignal,
): AsyncGenerator<PlanStreamEvent> {
  const response = await fetch(`${getApiUrl()}/api/v1/plan/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
