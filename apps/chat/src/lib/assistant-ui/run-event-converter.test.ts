import { beforeEach, describe, expect, it, vi } from "vitest";

const { subscribeChatRunMock, markUnreadMock } = vi.hoisted(() => ({
  subscribeChatRunMock: vi.fn(),
  markUnreadMock: vi.fn(),
}));

vi.mock("@/lib/chat-run-api", () => ({
  subscribeChatRun: subscribeChatRunMock,
}));
vi.mock("@/lib/dotamind-api", () => ({
  formatPlanResponse: vi.fn(),
  formatStreamError: vi.fn(),
  getChatSession: vi.fn(),
}));
vi.mock("./thread-unread", () => ({
  markDotaMindSessionUnread: markUnreadMock,
}));

import { streamDotaMindRun } from "./run-event-converter";

describe("streamDotaMindRun Checkpoint events", () => {
  beforeEach(() => {
    subscribeChatRunMock.mockReset();
    markUnreadMock.mockReset();
  });

  it("keeps the checkpoint and stops at waiting_input", async () => {
    subscribeChatRunMock.mockImplementation(async function* () {
      yield {
        run_id: "run-a",
        session_id: "session-a",
        sequence: 4,
        event: {
          type: "checkpoint",
          checkpoint: {
            checkpoint_type: "pandascore_match_selection",
            question: "请选择比赛",
            options: [{ id: "match-a", label: "8 月 20 日", value: { scheduled_date: "2026-08-20" } }],
            source_tool_call_id: "resolve_games",
            resume_node: "tools",
          },
        },
      };
      yield {
        run_id: "run-a",
        session_id: "session-a",
        sequence: 5,
        event: { type: "status", status: "waiting_input" },
      };
    });

    const results = [];
    for await (const result of streamDotaMindRun({
      browserId: "browser-a",
      runId: "run-a",
      sessionId: "session-a",
      requestId: "request-a",
      messageId: "message-a",
      abortSignal: new AbortController().signal,
    })) {
      results.push(result);
    }

    const runtime = results.at(-1)?.metadata?.custom?.dotamind;
    expect(runtime).toMatchObject({
      runId: "run-a",
      runtime: {
        status: "waiting_input",
        lastSequence: 5,
        checkpoint: { checkpoint_type: "pandascore_match_selection" },
      },
    });
    expect(markUnreadMock).not.toHaveBeenCalled();
  });

  it("resumes the same Run from the supplied event cursor", async () => {
    subscribeChatRunMock.mockImplementation(async function* () {
      yield {
        run_id: "run-a",
        session_id: "session-a",
        sequence: 12,
        event: { type: "status", status: "completed" },
      };
    });

    await streamDotaMindRun({
      browserId: "browser-a",
      runId: "run-a",
      sessionId: "session-a",
      requestId: "request-a",
      messageId: "message-resumed",
      after: 11,
      abortSignal: new AbortController().signal,
    }).next();

    expect(subscribeChatRunMock).toHaveBeenCalledWith(
      "browser-a",
      "run-a",
      11,
      expect.any(AbortSignal),
    );
  });
});
