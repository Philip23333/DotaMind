import type { ThreadMessage } from "@assistant-ui/react";

const DEFAULT_API_URL = "http://localhost:8001";

type PlanStatus =
  | "ok"
  | "clarification_required"
  | "insufficient_context"
  | "insufficient_tools"
  | "insufficient_evidence"
  | "error";

type AnswerItem = Record<string, unknown>;

type PlanResponse = {
  status?: PlanStatus;
  reason?: string;
  error_code?: string | null;
  answer?: {
    summary?: string;
    claims?: AnswerItem[];
    recommendations?: AnswerItem[];
    limitations?: AnswerItem[];
  } | null;
};

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

export async function askDotaMind(
  query: string,
  sessionId: string,
  abortSignal: AbortSignal,
): Promise<string> {
  const response = await fetch(`${getApiUrl()}/api/v1/plan`, {
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

  let payload: PlanResponse;
  try {
    payload = (await response.json()) as PlanResponse;
  } catch {
    throw new Error(`DotaMind API 返回了无法解析的响应（HTTP ${response.status}）。`);
  }

  if (!response.ok) {
    throw new Error(
      payload.reason?.trim() ||
        `DotaMind API 请求失败（HTTP ${response.status}）。`,
    );
  }

  return formatPlanResponse(payload);
}
