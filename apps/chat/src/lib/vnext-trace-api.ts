import { getApiUrl } from "./api-url";

export type SessionTraceSummary = {
  trace_id: string;
  request_id: string;
  status: "completed" | "failed" | "cancelled";
  recording_mode: "diagnostic" | "test";
  created_at: string;
  expires_at: string;
};

export async function listSessionTraces(
  browserId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionTraceSummary[]> {
  const response = await fetch(
    `${getApiUrl()}/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/traces`,
    {
      headers: { "X-DotaMind-Browser-Id": browserId },
      cache: "no-store",
      signal,
    },
  );
  if (!response.ok) {
    let reason = "Trace 列表加载失败。";
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "reason" in body) {
        const value = (body as { reason?: unknown }).reason;
        if (typeof value === "string" && value.trim()) reason = value;
      }
    } catch {
      // Keep the stable list error when the response does not contain JSON.
    }
    throw new Error(reason);
  }

  const body: unknown = await response.json();
  if (!body || typeof body !== "object" || !Array.isArray((body as { traces?: unknown }).traces)) {
    throw new Error("Trace 列表响应格式无效。");
  }
  const traces = (body as { traces: unknown[] }).traces;
  if (!traces.every(isSessionTraceSummary)) {
    throw new Error("Trace 列表包含无效记录。");
  }
  return traces;
}

function isSessionTraceSummary(value: unknown): value is SessionTraceSummary {
  if (!value || typeof value !== "object") return false;
  const trace = value as Record<string, unknown>;
  return (
    typeof trace.trace_id === "string" &&
    typeof trace.request_id === "string" &&
    (trace.status === "completed" || trace.status === "failed" || trace.status === "cancelled") &&
    (trace.recording_mode === "diagnostic" || trace.recording_mode === "test") &&
    typeof trace.created_at === "string" &&
    typeof trace.expires_at === "string"
  );
}
