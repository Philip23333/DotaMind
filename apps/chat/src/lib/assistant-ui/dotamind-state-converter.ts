import type {
  AssistantTransportCommand,
  AssistantTransportConnectionMetadata,
  MessageStatus,
  ThreadAssistantMessage,
  ThreadMessage,
  ThreadUserMessage,
} from "@assistant-ui/react";

import { DOTAMIND_ASSISTANT_METADATA_KEY } from "./migration-contract";
import {
  canonicalMessageId,
  type DotamindAssistantTransportEnvelope,
  type DotamindConnectionStatus,
  type DotamindMessageMetadata,
  type DotamindMessageRunMetadata,
  type DotamindProductRunState,
  type DotamindRequestConnection,
} from "./dotamind-run-state";

type TranscriptTurnIdentity = {
  turn_index?: number;
  request_id: string;
  user_query: string;
  created_at: string;
};

export type PendingDotaMindUserMessage = {
  session_id: string;
  request_id: string;
  user_query: string;
  command: AssistantTransportCommand;
  created_at: string;
};

export type DotaMindConversationHistory = {
  session_id: string;
  messages: readonly ThreadMessage[];
};

export type DotaMindStateConverterInput = {
  session_id: string;
  history: DotaMindConversationHistory;
  current_state: DotamindAssistantTransportEnvelope | null;
  pending_user: PendingDotaMindUserMessage | null;
  connection: DotamindRequestConnection | null;
  current_message_created_at?: string;
};

/**
 * The installed assistant-ui version keeps its converter result type internal.
 * This public-type-only shape is structurally compatible with its converter:
 * messages are actual ThreadMessage values and the other fields match its state.
 */
export type DotaMindAssistantTransportState = {
  messages: ThreadMessage[];
  isRunning: boolean;
  state?: DotamindAssistantTransportEnvelope | null;
};

const stableFallbackCreatedAt = "1970-01-01T00:00:00.000Z";
const completeStatus: MessageStatus = { type: "complete", reason: "stop" };

export function transcriptTurnsToCanonicalMessages<Turn extends TranscriptTurnIdentity>(
  turns: readonly Turn[],
  formatAssistantResponse: (turn: Turn) => string,
): ThreadMessage[] {
  return turns.flatMap((turn) => {
    const createdAt = parseCreatedAt(turn.created_at);
    const requestId = turn.request_id;
    const userMetadata: DotamindMessageMetadata = {
      request_id: requestId,
      source: "history",
    };
    const assistantMetadata: DotamindMessageMetadata = {
      request_id: requestId,
      source: "history",
      persistence: "saved",
      ...(turn.turn_index === undefined ? {} : { turn_index: turn.turn_index }),
    };

    return [
      createUserMessage(
        canonicalMessageId("user", requestId),
        turn.user_query,
        createdAt,
        userMetadata,
      ),
      createAssistantMessage(
        canonicalMessageId("assistant", requestId),
        formatAssistantResponse(turn),
        createdAt,
        completeStatus,
        assistantMetadata,
      ),
    ];
  });
}

/** Pure product-state conversion. Assistant-ui's connection metadata has no
 * request identity, so local lifecycle facts come from the keyed input instead. */
export function convertDotaMindState(
  input: DotaMindStateConverterInput,
  connectionMetadata: AssistantTransportConnectionMetadata,
): DotaMindAssistantTransportState {
  // Keep the assistant-ui converter signature, but do not apply unkeyed status
  // to a request when the current thread may contain consecutive messages.
  void connectionMetadata;
  assertSameSession(input);
  if (input.current_state) assertEnvelopeIdentity(input.current_state);

  const result: ThreadMessage[] = [];
  const positions = new Map<string, number>();
  const upsert = (message: ThreadMessage) => {
    const previousIndex = positions.get(message.id);
    if (previousIndex === undefined) {
      positions.set(message.id, result.length);
      result.push(message);
      return;
    }
    const existing = result[previousIndex];
    if (!existing) throw new Error("assistant-ui message index is inconsistent");
    result[previousIndex] = mergeMessages(existing, message);
  };

  for (const message of input.history.messages) upsert(message);

  if (input.current_state) {
    const envelope = input.current_state;
    const connectionStatus = messageConnectionStatus(input, envelope.request_id);
    upsert(
      createUserMessage(
        envelope.user_message.id,
        envelope.user_message.text,
        messageCreatedAt(input, envelope.request_id),
        transportUserMetadata(envelope, connectionStatusForRequest(input.connection, envelope.request_id)),
      ),
    );
    upsert(
      createAssistantMessage(
        envelope.run.assistant_message_id,
        envelope.run.answer.text,
        messageCreatedAt(input, envelope.request_id),
        assistantStatus(envelope.run, connectionStatus),
        transportAssistantMetadata(
          envelope,
          connectionStatusForRequest(input.connection, envelope.request_id),
        ),
      ),
    );
  }

  const pending = input.pending_user;
  let unconfirmedPendingRequestId: string | null = null;
  let unconfirmedPendingConnectionStatus: DotamindConnectionStatus | null = null;
  if (pending) {
    const pendingText = textFromPendingCommand(pending.command);
    if (pendingText !== pending.user_query) {
      throw new Error("pending user text does not match its AssistantTransport command");
    }
    if (input.current_state?.request_id === pending.request_id) {
      if (input.current_state.user_message.text !== pending.user_query) {
        throw new Error("pending request conflicts with its server-confirmed message");
      }
    }
    const existingUser = result.find(
      (message) => message.id === canonicalMessageId("user", pending.request_id),
    );
    if (existingUser && messageText(existingUser) !== pending.user_query) {
      throw new Error("pending request conflicts with a historical message identity");
    }
    // The caller supplies this only after associating the command with a stable
    // request ID. Do not infer identity from the transport's unrelated queue.
    const wasConfirmed =
      input.current_state?.request_id === pending.request_id ||
      (existingUser !== undefined && !isOptimisticUserMessage(existingUser));
    if (!wasConfirmed) {
      unconfirmedPendingRequestId = pending.request_id;
      const id = canonicalMessageId("user", pending.request_id);
      const connectionStatus = messageConnectionStatus(input, pending.request_id);
      unconfirmedPendingConnectionStatus = connectionStatus;
      const metadata: DotamindMessageMetadata = {
        request_id: pending.request_id,
        source: "pending",
        ...(connectionStatus === null
          ? {}
          : { connection_status: connectionStatus }),
      };
      upsert(
        createUserMessage(
          id,
          pending.user_query,
          parseCreatedAt(pending.created_at),
          metadata,
          true,
        ),
      );
      upsert(
        createAssistantMessage(
          canonicalMessageId("assistant", pending.request_id),
          "",
          parseCreatedAt(pending.created_at),
          pendingAssistantStatus(connectionStatus),
          metadata,
        ),
      );
    }
  }

  return {
    messages: result,
    isRunning: calculateIsRunning(
      input.current_state?.run ?? null,
      input.connection,
      unconfirmedPendingRequestId,
      unconfirmedPendingConnectionStatus,
      messageConnectionStatus(input, input.current_state?.request_id ?? null),
    ),
  };
}

function assertSameSession(input: DotaMindStateConverterInput): void {
  if (input.history.session_id !== input.session_id) {
    throw new Error("conversation history belongs to a different session");
  }
  if (input.current_state && input.current_state.session_id !== input.session_id) {
    throw new Error("AssistantTransport state belongs to a different session");
  }
  if (input.pending_user && input.pending_user.session_id !== input.session_id) {
    throw new Error("pending user message belongs to a different session");
  }
}

function assertEnvelopeIdentity(envelope: DotamindAssistantTransportEnvelope): void {
  if (envelope.run.request_id !== envelope.request_id) {
    throw new Error("AssistantTransport request identity is inconsistent");
  }
  if (envelope.user_message.id !== canonicalMessageId("user", envelope.request_id)) {
    throw new Error("AssistantTransport user message identity is inconsistent");
  }
  if (envelope.run.assistant_message_id !== canonicalMessageId("assistant", envelope.request_id)) {
    throw new Error("AssistantTransport assistant message identity is inconsistent");
  }
}

function createUserMessage(
  id: string,
  text: string,
  createdAt: Date,
  metadata: DotamindMessageMetadata,
  isOptimistic = false,
): ThreadUserMessage {
  return {
    id,
    role: "user",
    content: [{ type: "text", text }],
    attachments: [],
    createdAt,
    metadata: {
      isOptimistic,
      custom: { [DOTAMIND_ASSISTANT_METADATA_KEY]: metadata },
    },
  };
}

function createAssistantMessage(
  id: string,
  text: string,
  createdAt: Date,
  status: MessageStatus,
  metadata: DotamindMessageMetadata,
): ThreadAssistantMessage {
  return {
    id,
    role: "assistant",
    content: [{ type: "text", text }],
    status,
    createdAt,
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: { [DOTAMIND_ASSISTANT_METADATA_KEY]: metadata },
    },
  };
}

function transportUserMetadata(
  envelope: DotamindAssistantTransportEnvelope,
  connectionStatus: DotamindConnectionStatus | null,
): DotamindMessageMetadata {
  return {
    request_id: envelope.request_id,
    source: "transport",
    ...(connectionStatus === null ? {} : { connection_status: connectionStatus }),
  };
}

function transportAssistantMetadata(
  envelope: DotamindAssistantTransportEnvelope,
  connectionStatus: DotamindConnectionStatus | null,
): DotamindMessageMetadata {
  const answer: DotamindMessageRunMetadata["answer"] = {
    attempt_id: envelope.run.answer.attempt_id,
    kind: envelope.run.answer.kind,
    status: envelope.run.answer.status,
  };
  const run: DotamindMessageRunMetadata = {
    ...envelope.run,
    answer,
    activity: envelope.run.activity.map((item) => ({ ...item })),
    error: envelope.run.error ? { ...envelope.run.error } : null,
  };
  return {
    request_id: envelope.request_id,
    source: "transport",
    persistence: envelope.run.persistence,
    run,
    ...(envelope.turn_index === null ? {} : { turn_index: envelope.turn_index }),
    ...(envelope.trace === null ? {} : { trace: { ...envelope.trace } }),
    ...(connectionStatus === null ? {} : { connection_status: connectionStatus }),
  };
}

function assistantStatus(
  run: DotamindProductRunState,
  connectionStatus: DotamindConnectionStatus | null,
): MessageStatus {
  if (run.status === "failed") return { type: "incomplete", reason: "error" };
  if (run.status === "cancelled") return { type: "incomplete", reason: "cancelled" };
  if (run.status === "completed" && (run.persistence === "saved" || run.persistence === "failed")) {
    return { type: "complete", reason: "stop" };
  }
  if (connectionStatus === "cancelled") return { type: "incomplete", reason: "cancelled" };
  if (connectionStatus === "error") return { type: "incomplete", reason: "error" };
  if (connectionStatus === "ended") return { type: "incomplete", reason: "other" };
  return { type: "running" };
}

function pendingAssistantStatus(
  connectionStatus: DotamindConnectionStatus | null,
): MessageStatus {
  if (connectionStatus === "cancelled") return { type: "incomplete", reason: "cancelled" };
  if (connectionStatus === "error") return { type: "incomplete", reason: "error" };
  if (connectionStatus === "ended") return { type: "incomplete", reason: "other" };
  return { type: "running" };
}

function calculateIsRunning(
  run: DotamindProductRunState | null,
  connection: DotamindRequestConnection | null,
  unconfirmedPendingRequestId: string | null,
  pendingConnectionStatus: DotamindConnectionStatus | null,
  runConnectionStatus: DotamindConnectionStatus | null,
): boolean {
  if (unconfirmedPendingRequestId !== null) {
    return !isConnectionTerminal(pendingConnectionStatus);
  }

  if (run && isRunSettled(run)) return false;
  if (run) {
    if (isConnectionTerminal(runConnectionStatus)) return false;
    if (runConnectionStatus === "sending") return true;
    return (
      run.status === "running" ||
      (run.status === "completed" && (run.persistence === "pending" || run.persistence === "saving"))
    );
  }
  return connection?.status === "sending";
}

function isConnectionTerminal(status: DotamindConnectionStatus | null): boolean {
  return status === "ended" || status === "cancelled" || status === "error";
}

function connectionStatusForRequest(
  connection: DotamindRequestConnection | null,
  requestId: string,
): DotamindConnectionStatus | null {
  return connection?.request_id === requestId ? connection.status : null;
}

function messageConnectionStatus(
  input: DotaMindStateConverterInput,
  requestId: string | null,
): DotamindConnectionStatus | null {
  if (requestId === null) return null;
  const current = connectionStatusForRequest(input.connection, requestId);
  if (current !== null) return current;

  const messageIds = [
    canonicalMessageId("assistant", requestId),
    canonicalMessageId("user", requestId),
  ];
  for (const messageId of messageIds) {
    const message = input.history.messages.find((item) => item.id === messageId);
    if (!message) continue;
    const metadata = objectValue(message.metadata.custom[DOTAMIND_ASSISTANT_METADATA_KEY]);
    if (metadata.request_id !== requestId || !isConnectionStatus(metadata.connection_status)) continue;
    return metadata.connection_status;
  }
  return null;
}

function isConnectionStatus(value: unknown): value is DotamindConnectionStatus {
  return value === "sending" || value === "ended" || value === "cancelled" || value === "error";
}

function isOptimisticUserMessage(message: ThreadMessage): boolean {
  return message.role === "user" && message.metadata.isOptimistic === true;
}

function isRunSettled(run: DotamindProductRunState): boolean {
  return (
    run.status === "failed" ||
    run.status === "cancelled" ||
    (run.status === "completed" && (run.persistence === "saved" || run.persistence === "failed"))
  );
}

function textFromPendingCommand(command: AssistantTransportCommand): string {
  if (command.type !== "add-message" || command.message.role !== "user" || command.sourceId !== null) {
    throw new Error("only a new user add-message command can be converted");
  }
  if (command.message.parts.some((part) => part.type !== "text")) {
    throw new Error("only text user messages can be converted");
  }
  return command.message.parts.map((part) => (part.type === "text" ? part.text : "")).join("");
}

function messageText(message: ThreadMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function mergeMessages(existing: ThreadMessage, incoming: ThreadMessage): ThreadMessage {
  if (existing.role !== incoming.role) {
    throw new Error(`canonical message ${existing.id} changed role`);
  }
  if (existing.role === "user") {
    if (incoming.role !== "user") throw new Error(`canonical message ${existing.id} changed role`);
    if (messageText(existing) !== messageText(incoming)) {
      throw new Error(`canonical user message ${existing.id} changed text`);
    }
    return {
      ...existing,
      ...incoming,
      createdAt: existing.createdAt,
      metadata: {
        ...existing.metadata,
        ...incoming.metadata,
        custom: mergeCustomMetadata(existing.metadata.custom, incoming.metadata.custom),
      },
    };
  }
  if (incoming.role !== "assistant") throw new Error(`canonical message ${existing.id} changed role`);
  return {
    ...existing,
    ...incoming,
    createdAt: existing.createdAt,
    metadata: {
      ...existing.metadata,
      ...incoming.metadata,
      custom: mergeCustomMetadata(existing.metadata.custom, incoming.metadata.custom),
    },
  };
}

function mergeCustomMetadata(
  existingCustom: Record<string, unknown>,
  incomingCustom: Record<string, unknown>,
): Record<string, unknown> {
  const oldDotaMind = objectValue(existingCustom[DOTAMIND_ASSISTANT_METADATA_KEY]);
  const newDotaMind = objectValue(incomingCustom[DOTAMIND_ASSISTANT_METADATA_KEY]);
  const mergedDotaMind = { ...oldDotaMind, ...newDotaMind };
  if (newDotaMind.trace === undefined && oldDotaMind.trace !== undefined) {
    mergedDotaMind.trace = oldDotaMind.trace;
  }

  return {
    ...existingCustom,
    ...incomingCustom,
    [DOTAMIND_ASSISTANT_METADATA_KEY]: mergedDotaMind,
  };
}

function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function messageCreatedAt(
  input: DotaMindStateConverterInput,
  requestId: string,
): Date {
  const pending = input.pending_user;
  if (pending?.request_id === requestId) return parseCreatedAt(pending.created_at);
  const existing = input.history.messages.find(
    (message) =>
      message.id === canonicalMessageId("user", requestId) ||
      message.id === canonicalMessageId("assistant", requestId),
  );
  if (existing) return existing.createdAt;
  return parseOptionalCreatedAt(input.current_message_created_at);
}

function parseOptionalCreatedAt(value: string | undefined): Date {
  return value === undefined ? new Date(stableFallbackCreatedAt) : parseCreatedAt(value);
}

function parseCreatedAt(value: string): Date {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error("chat message has an invalid created_at timestamp");
  return date;
}

export { DOTAMIND_ASSISTANT_METADATA_KEY };
