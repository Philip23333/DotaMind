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

  it("delivers the final answer before updating unread thread metadata", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "completed", content: "完整回答", turn_index: 1 };
    });

    const stream = streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "question",
      abortSignal: new AbortController().signal,
    });

    expect(text((await stream.next()).value as ChatModelRunResult)).toBe("完整回答");
    expect(markUnreadMock).not.toHaveBeenCalled();
    expect((await stream.next()).done).toBe(true);
    expect(markUnreadMock).toHaveBeenCalledWith("session-a");
  });

  it("decorates only the completed final text with persisted catalog entities", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "delta", text: "不朽" };
      yield { type: "delta", text: "尸王" };
      yield {
        type: "completed",
        content: "不朽尸王（Undying）是一名英雄。",
        turn_index: 1,
        catalog_visual_entities: [
          {
            kind: "hero",
            imagePath: "/api/v1/assets/dota/heroes/85.png",
            label: "不朽尸王",
            names: ["不朽尸王", "Undying"],
          },
        ],
      };
    });

    const results = [];
    for await (const result of streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "介绍不朽尸王",
      abortSignal: new AbortController().signal,
    })) {
      results.push(result);
    }

    expect(results.map(text)).toEqual([
      "不朽",
      "不朽尸王",
      "![不朽尸王](http://localhost:8001/api/v1/assets/dota/heroes/85.png#dota-size=md)不朽尸王（Undying）是一名英雄。",
    ]);
  });

  it("rejects an error event without marking the thread completed", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "error", error_code: "agent_runtime_error", reason: "runtime failed" };
    });

    const consume = async () => {
      for await (const _result of streamVNextChatMessage({
        browserId: "browser-a",
        sessionId: "session-a",
        query: "question",
        abortSignal: new AbortController().signal,
      })) {
        void _result;
      }
    };

    await expect(consume()).rejects.toThrow("本次请求未完成：runtime failed");
    expect(markUnreadMock).not.toHaveBeenCalled();
  });

  it("preserves a failed-run trace reference in assistant metadata", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield {
        type: "error",
        error_code: "max_tool_calls_exceeded",
        reason: "too many calls",
        trace: { trace_id: "trace-1", expires_at: "2026-08-31T12:00:00Z" },
      };
    });

    const stream = streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "question",
      abortSignal: new AbortController().signal,
    });

    expect(((await stream.next()).value as ChatModelRunResult).metadata?.custom).toEqual({
      dotamind: { trace: { trace_id: "trace-1", expires_at: "2026-08-31T12:00:00Z" } },
    });
    await expect(stream.next()).rejects.toThrow("本次请求未完成：too many calls");
  });

  it("rejects a truncated stream instead of treating the partial answer as complete", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield { type: "delta", text: "前几个字" };
    });

    const stream = streamVNextChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      query: "question",
      abortSignal: new AbortController().signal,
    });

    expect(text((await stream.next()).value as ChatModelRunResult)).toBe("前几个字");
    await expect(stream.next()).rejects.toThrow("连接在收到最终结果前结束");
    expect(markUnreadMock).not.toHaveBeenCalled();
  });

  it("preserves a completed trace reference without changing completed text", async () => {
    streamChatMessageMock.mockImplementation(async function* () {
      yield {
        type: "completed",
        content: "answer",
        turn_index: 1,
        trace: { trace_id: "trace-2", expires_at: "2026-09-26T00:00:00Z" },
      };
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

    expect(results.map(text)).toEqual(["answer"]);
    expect(results[0]?.metadata?.custom).toEqual({
      dotamind: { trace: { trace_id: "trace-2", expires_at: "2026-09-26T00:00:00Z" } },
    });
  });
});
