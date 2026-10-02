import { afterEach, describe, expect, it, vi } from "vitest";

import { getRecentSeries, type RecentSeriesResponse } from "./home-api";

const fresh: RecentSeriesResponse = {
  status: "fresh",
  items: [{
    series_id: 12345,
    name: "The International",
    lifecycle: "past",
    begin_at: "2026-09-01T00:00:00Z",
    end_at: "2026-09-10T00:00:00Z",
    champion_name: "Team Example",
  }],
  retrieved_at: "2026-09-10T00:00:00Z",
  last_attempt_at: "2026-09-10T00:00:00Z",
  last_error: null,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("getRecentSeries", () => {
  it("requests the shared endpoint with GET, no-store, and the caller signal", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(fresh));
    vi.stubGlobal("fetch", fetchMock);

    await getRecentSeries(controller.signal);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8001/api/v1/home/recent-series",
      { method: "GET", cache: "no-store", signal: controller.signal },
    );
  });

  it.each(["fresh", "stale", "unavailable"] as const)(
    "accepts a %s response including an empty valid result",
    async (status) => {
      const result = { ...fresh, status, items: status === "unavailable" ? [] : fresh.items };
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(result)));
      await expect(getRecentSeries()).resolves.toEqual(result);
    },
  );

  it("does not expose provider errors from an HTTP failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "private upstream data" }, 503)));
    await expect(getRecentSeries()).rejects.toThrow("赛事列表暂时不可用。");
    await expect(getRecentSeries()).rejects.not.toThrow("private upstream data");
  });

  it("rejects invalid JSON and malformed response shapes", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response("<html>not json</html>"))
      .mockResolvedValueOnce(jsonResponse({ ...fresh, items: [{ ...fresh.items[0], series_id: Number.MAX_SAFE_INTEGER + 1 }] })));

    await expect(getRecentSeries()).rejects.toThrow("近期赛事响应无效。");
    await expect(getRecentSeries()).rejects.toThrow("近期赛事响应无效。");
  });
});
