import { describe, expect, it, vi } from "vitest";

import { createRunForInitializedThread } from "./thread-initialization";

describe("DotaMind model adapter", () => {
  it("waits for a new thread to initialize before creating its first Run", async () => {
    let finishInitialization: ((value: { remoteId: string }) => void) | undefined;
    const initializeThread = vi.fn(
      () =>
        new Promise<{ remoteId: string }>((resolve) => {
          finishInitialization = resolve;
        }),
    );
    const run = { run_id: "run-a", request_id: "request-a" };
    const createRun = vi.fn(async () => run);

    const pending = createRunForInitializedThread({
      browserId: "browser-a",
      query: "first message",
      initializeThread,
      createRun,
    });

    expect(initializeThread).toHaveBeenCalledOnce();
    expect(createRun).not.toHaveBeenCalled();

    finishInitialization?.({ remoteId: "session-a" });

    await expect(pending).resolves.toEqual({ run, sessionId: "session-a" });
    expect(createRun).toHaveBeenCalledOnce();
    expect(createRun).toHaveBeenCalledWith("browser-a", "session-a", "first message");
  });
});
