import { describe, expect, it } from "vitest";

import type { ChatRunSummary } from "./dotamind-api";
import { chatRunReducer, EMPTY_CHAT_RUN_STORE } from "./chat-run-store";

function summary(runId: string, sessionId: string, status: ChatRunSummary["status"]): ChatRunSummary {
  return {
    run_id: runId,
    session_id: sessionId,
    request_id: `request-${runId}`,
    status,
    user_query: `query-${runId}`,
    last_event_sequence: 0,
    result_turn_id: null,
    error_code: null,
    created_at: "2026-08-05T00:00:00Z",
    started_at: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    completed_at: null,
  };
}

function statusEvent(runId: string, sessionId: string, sequence: number, status: ChatRunSummary["status"]) {
  return {
    type: "event" as const,
    item: {
      run_id: runId,
      session_id: sessionId,
      sequence,
      event: { type: "status" as const, status },
    },
  };
}

describe("chatRunReducer", () => {
  it("deduplicates sequences and rejects cross-session events", () => {
    const registered = chatRunReducer(
      EMPTY_CHAT_RUN_STORE,
      { type: "register", summary: summary("run-a", "session-a", "running") },
    );
    const first = chatRunReducer(registered, statusEvent("run-a", "session-a", 1, "completed"));
    const duplicate = chatRunReducer(first, statusEvent("run-a", "session-a", 1, "failed"));
    const wrongSession = chatRunReducer(first, statusEvent("run-a", "session-b", 2, "failed"));

    expect(first.runsById["run-a"].summary.status).toBe("completed");
    expect(first.runsById["run-a"].lastEventSequence).toBe(1);
    expect(duplicate).toEqual(first);
    expect(wrongSession).toEqual(first);
  });

  it("keeps concurrent sessions isolated and marks only the completed run unread", () => {
    let state = chatRunReducer(
      EMPTY_CHAT_RUN_STORE,
      { type: "register", summary: summary("run-a", "session-a", "running") },
    );
    state = chatRunReducer(state, { type: "register", summary: summary("run-b", "session-b", "running") });
    state = chatRunReducer(state, statusEvent("run-a", "session-a", 1, "completed"));

    expect(state.activeRunIdBySession["session-a"]).toBeUndefined();
    expect(state.activeRunIdBySession["session-b"]).toBe("run-b");
    expect(state.runsById["run-b"].summary.status).toBe("running");
    expect(state.unreadRunCountBySession["session-a"]).toBe(1);
    expect(state.unreadRunCountBySession["session-b"]).toBeUndefined();
  });

  it("clears all Run and unread state for a deleted session", () => {
    let state = chatRunReducer(
      EMPTY_CHAT_RUN_STORE,
      { type: "register", summary: summary("run-a", "session-a", "completed") },
    );
    state = chatRunReducer(state, { type: "mark_unread", sessionId: "session-a" });
    state = chatRunReducer(state, { type: "clear_session", sessionId: "session-a" });

    expect(state.runsById).toEqual({});
    expect(state.activeRunIdBySession).toEqual({});
    expect(state.unreadRunCountBySession).toEqual({});
  });
});
