import { describe, expect, it } from "vitest";

import {
  mapDotaMindSessionToThread,
  pendingRunMessageIds,
  shouldCancelDotaMindRun,
} from "./migration-contract";

describe("assistant-ui migration contract", () => {
  it("maps one assistant-ui thread to one DotaMind session", () => {
    expect(mapDotaMindSessionToThread("session-a")).toEqual({
      threadId: "session-a",
      sessionId: "session-a",
    });
  });

  it("keeps pending Run message ids stable across recovery", () => {
    expect(pendingRunMessageIds("run-a")).toEqual({
      userMessageId: "run-a:user",
      assistantMessageId: "run-a:assistant",
    });
  });

  it("only explicit user stop is allowed to cancel a Run", () => {
    expect(shouldCancelDotaMindRun("subscription")).toBe(false);
    expect(shouldCancelDotaMindRun("user_stop")).toBe(true);
  });
});
