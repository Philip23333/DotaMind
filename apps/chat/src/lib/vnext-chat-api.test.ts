import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChatMessage } from "./vnext-chat-api";

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
        controller.close();
      },
    }),
  );
}

describe("vNext chat API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts one message and reassembles NDJSON split across network chunks", async () => {
    const fetchMock = vi.fn(async () =>
      streamResponse([
        '{"type":"delta","text":"A',
        'me"}\n{"type":"completed","content":"Ame","turn_index":1}\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const events = [];
    for await (const event of streamChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      requestId: "request-a",
      query: "Ame 在哪队？",
      signal: new AbortController().signal,
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: "delta", text: "Ame" },
      { type: "completed", content: "Ame", turn_index: 1 },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8001/api/v1/chat/sessions/session-a/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request_id: "request-a", query: "Ame 在哪队？" }),
        headers: {
          "Content-Type": "application/json",
          "X-DotaMind-Browser-Id": "browser-a",
        },
      }),
    );
  });

  it("accepts only local catalog visual entities on completed events", async () => {
    const fetchMock = vi.fn(async () =>
      streamResponse([
        '{"type":"completed","content":"不朽尸王","turn_index":1,"catalog_visual_entities":[{"kind":"hero","imagePath":"/api/v1/assets/dota/heroes/85.png","label":"不朽尸王","names":["不朽尸王","Undying"]}]}\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const events = [];
    for await (const event of streamChatMessage({
      browserId: "browser-a",
      sessionId: "session-a",
      requestId: "request-a",
      query: "介绍不朽尸王",
      signal: new AbortController().signal,
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "completed",
        content: "不朽尸王",
        turn_index: 1,
        catalog_visual_entities: [
          {
            kind: "hero",
            imagePath: "/api/v1/assets/dota/heroes/85.png",
            label: "不朽尸王",
            names: ["不朽尸王", "Undying"],
          },
        ],
      },
    ]);
  });

  it("rejects non-local catalog visual entity paths", async () => {
    const fetchMock = vi.fn(async () =>
      streamResponse([
        '{"type":"completed","content":"answer","turn_index":1,"catalog_visual_entities":[{"kind":"hero","imagePath":"https://example.test/hero.png","label":"hero","names":["hero"]}]}\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const consume = async () => {
      for await (const _event of streamChatMessage({
        browserId: "browser-a",
        sessionId: "session-a",
        requestId: "request-a",
        query: "question",
        signal: new AbortController().signal,
      })) {
        // Consume the stream so parser validation is reached.
      }
    };

    await expect(consume()).rejects.toThrow("无效实体展示数据");
  });
});
