import { afterEach, describe, expect, it, vi } from "vitest";

import { listSessionTraces } from "./vnext-trace-api";

describe("session trace API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists metadata for the selected remote session with browser identity", async () => {
    const responseBody = {
      traces: [
        {
          trace_id: "trace-1",
          request_id: "request-1",
          status: "completed",
          recording_mode: "test",
          created_at: "2026-09-23T00:00:00Z",
          expires_at: "2026-09-26T00:00:00Z",
        },
      ],
    };
    const fetchMock = vi.fn(async () => Response.json(responseBody));
    vi.stubGlobal("fetch", fetchMock);

    const sessionId = "00000000-0000-4000-8000-000000000001";
    const traces = await listSessionTraces("browser-a", sessionId);

    expect(traces).toEqual(responseBody.traces);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8001/api/v1/chat/sessions/${sessionId}/traces`,
      expect.objectContaining({
        headers: { "X-DotaMind-Browser-Id": "browser-a" },
        cache: "no-store",
      }),
    );
  });

  it("returns a retryable error for failed list requests", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ reason: "Trace storage unavailable" }, { status: 503 })),
    );

    await expect(listSessionTraces("browser-a", "session-a")).rejects.toThrow(
      "Trace storage unavailable",
    );
  });

  it("rejects malformed list metadata", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ traces: [{ trace_id: "trace-1" }] })));

    await expect(listSessionTraces("browser-a", "session-a")).rejects.toThrow(
      "无效记录",
    );
  });
});
