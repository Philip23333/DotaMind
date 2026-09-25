import type { TraceRef } from "../vnext-chat-api";

export type DotamindRunStatus = "running" | "completed" | "failed" | "cancelled";
export type DotamindRunStage = "execution" | "answer";
export type DotamindAnswerKind = "primary" | "degraded" | "deterministic";
export type DotamindAnswerStatus = "pending" | "streaming" | "ready" | "interrupted";
export type DotamindPersistenceStatus = "pending" | "saving" | "saved" | "failed";

export type DotamindRunError = {
  scope: "execution" | "persistence";
  code: string;
  message: string;
};

export type DotamindStageActivity = {
  kind: "stage";
  id: string;
  stage: DotamindRunStage;
};

export type DotamindToolActivity = {
  kind: "tool";
  id: string;
  tool_name: string;
  status: "running" | "completed" | "failed";
  duration_seconds: number | null;
  error_code: string | null;
};

export type DotamindActivityItem = DotamindStageActivity | DotamindToolActivity;

export type DotamindAnswerState = {
  attempt_id: string | null;
  kind: DotamindAnswerKind | null;
  text: string;
  status: DotamindAnswerStatus;
};

export type DotamindProductRunState = {
  request_id: string;
  assistant_message_id: string;
  status: DotamindRunStatus;
  stage: DotamindRunStage;
  activity: DotamindActivityItem[];
  omitted_activity_count: number;
  answer: DotamindAnswerState;
  persistence: DotamindPersistenceStatus;
  error: DotamindRunError | null;
};

export type DotamindAssistantTransportEnvelope = {
  session_id: string;
  request_id: string;
  user_message: {
    id: string;
    text: string;
  };
  run: DotamindProductRunState;
  turn_index: number | null;
  trace: TraceRef | null;
};

export type DotamindConnectionStatus = "sending" | "ended" | "cancelled" | "error";
export type DotamindRequestConnection = {
  request_id: string;
  status: DotamindConnectionStatus;
};

export type DotamindMessageRunMetadata = Omit<DotamindProductRunState, "answer"> & {
  answer: Omit<DotamindAnswerState, "text">;
};

/** Structured presentation metadata; canonical answer text stays in message content. */
export type DotamindMessageMetadata = {
  request_id: string;
  source: "history" | "pending" | "transport";
  persistence?: DotamindPersistenceStatus;
  run?: DotamindMessageRunMetadata;
  turn_index?: number;
  trace?: TraceRef;
  connection_status?: DotamindConnectionStatus | null;
};

export function canonicalMessageId(role: "user" | "assistant", requestId: string): string {
  return `${role}:${requestId}`;
}
