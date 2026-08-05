export type AssistantUiAbortOrigin = "subscription" | "user_stop";

export type AssistantUiThreadMapping = {
  threadId: string;
  sessionId: string;
};

/**
 * The browser may stop observing a Run without changing the durable Run state.
 * Only an explicit stop action is allowed to call the cancel endpoint.
 */
export function shouldCancelDotaMindRun(origin: AssistantUiAbortOrigin): boolean {
  return origin === "user_stop";
}

export function mapDotaMindSessionToThread(sessionId: string): AssistantUiThreadMapping {
  return { threadId: sessionId, sessionId };
}

export function pendingRunMessageIds(runId: string): {
  userMessageId: string;
  assistantMessageId: string;
} {
  return {
    userMessageId: `${runId}:user`,
    assistantMessageId: `${runId}:assistant`,
  };
}

export const DOTAMIND_ASSISTANT_METADATA_KEY = "dotamind";
