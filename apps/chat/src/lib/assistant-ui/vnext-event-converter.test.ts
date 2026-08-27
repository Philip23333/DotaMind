import type { ChatModelRunResult } from "@assistant-ui/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { streamChatMessageMock, markUnreadMock } = vi.hoisted(() => ({
  streamChatMessageMock: vi.fn(),
  markUnreadMock: vi.fn(),
}));

vi.mock("@/lib/vnext-chat-api", () => ({ streamChatMessage: streamChatMessageMock }));
vi.mock("./thread-unread", () => ({ markDotaMindSessionUnread: markUnreadMock }));

import { streamVNextChatMessage } from "./vnext-event-converter";

function text(result: ChatModelRunResult): string | undefined {
  const part = result.content?.[0];
  return part?.type === "text" ? part.text : undefined;
}

describe("vNext event converter", () => {
  beforeEach(() => {
    streamChatMessageMock.mockReset();
    markUnreadMock.mockReset();
  });

  it("accumulates deltas and finishes only on a completed event", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "delta", text: "A" };
      yield { type: "delta", text: "me" };
      yield { type: "completed", content: "Ame 在 Xtreme Gaming。", turn_index: 1 };
    });

    const results = [];
    for await (const result of streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "Ame 在哪队？",
      abortSignal: new AbortController().signal,
    })) {
      results.push(result);
    }

    expect(results.map(text)).toEqual([
      "A",
      "Ame",
      "Ame 在 Xtreme Gaming。",
    ]);
    expect(markUnreadMock).toHaveBeenCalledWith("session-a");
  });

  it("renders an error event without marking the thread completed", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "error", error_code: "max_steps_exceeded", reason: "too many steps" };
    });

    const results = [];
    for await (const result of streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "question",
      abortSignal: new AbortController().signal,
    })) {
      results.push(result);
    }

    expect(results.map(text)).toEqual([
      "本次请求未完成：too many steps",
    ]);
    expect(markUnreadMock).not.toHaveBeenCalled();
  });
});
