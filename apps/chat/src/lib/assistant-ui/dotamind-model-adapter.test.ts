import { describe, expect, it, vi } from "vitest";

import { initializeThreadForMessage } from "./thread-initialization";

describe("DotaMind model adapter", () => {
  it("waits for a new thread to initialize before sending its first message", async () => {
    let finishInitialization: ((value: { remoteId: string }) => void) | undefined;
    const initializeThread = vi.fn(
      () =>
        new Promise<{ remoteId: string }>((resolve) => {
          finishInitialization = resolve;
        }),
    );
    const pending = initializeThreadForMessage({
      initializeThread,
    });

    expect(initializeThread).toHaveBeenCalledOnce();

    finishInitialization?.({ remoteId: "session-a" });

    await expect(pending).resolves.toBe("session-a");
  });
});
