import { afterEach, describe, expect, it, vi } from "vitest";

import { resumeChatRun } from "./chat-run-api";

describe("chat-run resume API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends only the persisted checkpoint identity", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ run: { run_id: "run-a", status: "queued" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      resumeChatRun("browser-a", "run-a", "pandascore_match_selection", "playoffs_2026_08_20"),
    ).resolves.toEqual({ run_id: "run-a", status: "queued" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8001/api/v1/chat/runs/run-a/resume",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          checkpoint_type: "pandascore_match_selection",
          option_id: "playoffs_2026_08_20",
        }),
        headers: {
          "Content-Type": "application/json",
          "X-DotaMind-Browser-Id": "browser-a",
        },
      }),
    );
  });
});
