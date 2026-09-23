import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadTrace, TraceExpiredError } from "./trace-download";

describe("trace download", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("exposes expired traces as a distinct retry result", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 410 })));

    await expect(downloadTrace("browser-a", "trace-1")).rejects.toBeInstanceOf(
      TraceExpiredError,
    );
  });

  it("keeps other download failures retryable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));

    await expect(downloadTrace("browser-a", "trace-1")).rejects.toThrow("Trace 下载失败");
  });
});
