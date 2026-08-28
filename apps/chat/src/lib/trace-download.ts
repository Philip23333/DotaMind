import { getApiUrl } from "./api-url";

export class TraceExpiredError extends Error {}

export async function downloadTrace(browserId: string, traceId: string): Promise<void> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/traces/${traceId}`, {
    headers: { "X-DotaMind-Browser-Id": browserId },
  });
  if (response.status === 410) throw new TraceExpiredError();
  if (!response.ok) throw new Error("Trace 下载失败。");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `dotamind-trace-${traceId}.zip`;
  link.click();
  URL.revokeObjectURL(url);
}
