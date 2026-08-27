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
});
