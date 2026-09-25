import type {
  AssistantTransportCommand,
  AssistantTransportConnectionMetadata,
  ThreadAssistantMessage,
  ThreadMessage,
} from "@assistant-ui/react";
import { describe, expect, it } from "vitest";

import {
  canonicalMessageId,
  type DotamindAssistantTransportEnvelope,
  type DotamindMessageMetadata,
  type DotamindProductRunState,
} from "./dotamind-run-state";
import {
  convertDotaMindState,
  transcriptTurnsToCanonicalMessages,
  type DotaMindStateConverterInput,
  type PendingDotaMindUserMessage,
} from "./dotamind-state-converter";

const connection: AssistantTransportConnectionMetadata = {
  pendingCommands: [],
  isSending: false,
  toolStatuses: {},
};

function addUserCommand(text: string): AssistantTransportCommand {
  return {
    type: "add-message",
    message: { role: "user", parts: [{ type: "text", text }] },
    parentId: null,
    sourceId: null,
  };
}

const pendingCommand = addUserCommand("同一句问题");

function runState(
  overrides: Partial<DotamindProductRunState> = {},
): DotamindProductRunState {
  return {
    request_id: "request-a",
    assistant_message_id: canonicalMessageId("assistant", "request-a"),
    status: "running",
    stage: "answer",
    activity: [],
    omitted_activity_count: 0,
    answer: {
      attempt_id: "attempt-primary",
      kind: "primary",
      text: "实时正文",
      status: "streaming",
    },
    persistence: "pending",
    error: null,
    ...overrides,
  };
}

function envelope(
  overrides: Partial<DotamindAssistantTransportEnvelope> = {},
): DotamindAssistantTransportEnvelope {
  const { run, ...envelopeOverrides } = overrides;
  const runOverrides: Partial<DotamindProductRunState> = run ?? {};
  const requestId = envelopeOverrides.request_id ?? runOverrides.request_id ?? "request-a";
  return {
    session_id: "session-a",
    request_id: requestId,
    user_message: {
      id: canonicalMessageId("user", requestId),
      text: "同一句问题",
    },
    run: runState({ ...runOverrides, request_id: requestId,
      assistant_message_id: canonicalMessageId("assistant", requestId) }),
    turn_index: null,
    trace: null,
    ...envelopeOverrides,
  };
}

function pendingUser(
  overrides: Partial<PendingDotaMindUserMessage> = {},
): PendingDotaMindUserMessage {
  const userQuery = overrides.user_query ?? "同一句问题";
  return {
    session_id: "session-a",
    request_id: "request-a",
    created_at: "2026-09-25T02:00:00.000Z",
    ...overrides,
    user_query: userQuery,
    command: overrides.command ?? addUserCommand(userQuery),
  };
}

function input(
  overrides: Partial<DotaMindStateConverterInput> = {},
): DotaMindStateConverterInput {
  return {
    session_id: "session-a",
    history: { session_id: "session-a", messages: [] },
    current_state: null,
    pending_user: null,
    connection: null,
    current_message_created_at: "2026-09-25T02:00:00.000Z",
    ...overrides,
  };
}

function historyMessages(
  turns: Array<{ request_id: string; user_query: string; summary: string; turn_index?: number }>,
): ThreadMessage[] {
  return transcriptTurnsToCanonicalMessages(
    turns.map((turn) => ({
      request_id: turn.request_id,
      user_query: turn.user_query,
      created_at: "2026-09-24T12:00:00.000Z",
      turn_index: turn.turn_index,
      summary: turn.summary,
    })),
    (turn) => turn.summary,
  );
}

function assistant(messages: readonly ThreadMessage[], requestId = "request-a"): ThreadAssistantMessage {
  const found = messages.find((message) => message.id === canonicalMessageId("assistant", requestId));
  if (!found || found.role !== "assistant") throw new Error("assistant message was not produced");
  return found;
}

function userMessage(messages: readonly ThreadMessage[], requestId = "request-a"): ThreadMessage {
  const found = messages.find((message) => message.id === canonicalMessageId("user", requestId));
  if (!found || found.role !== "user") throw new Error("user message was not produced");
  return found;
}

function text(message: ThreadMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function productMetadata(message: ThreadMessage): DotamindMessageMetadata {
  const value = message.metadata.custom.dotamind;
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !("request_id" in value) ||
    !("source" in value)
  ) {
    throw new Error("DotaMind message metadata is missing");
  }
  return value as DotamindMessageMetadata;
}

function convert(
  value: DotaMindStateConverterInput,
  metadata: AssistantTransportConnectionMetadata = connection,
) {
  return convertDotaMindState(value, metadata);
}

describe("convertDotaMindState", () => {
  it("uses the request ID for historical user and assistant identities and preserves pairing order", () => {
    const messages = historyMessages([
      { request_id: "request-17", user_query: "问题", summary: "回答", turn_index: 3 },
    ]);

    expect(messages.map((message) => message.id)).toEqual([
      "user:request-17",
      "assistant:request-17",
    ]);
    expect(messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(messages[1]?.metadata.custom.dotamind).toMatchObject({
      request_id: "request-17",
      persistence: "saved",
      turn_index: 3,
    });
  });

  it("appends one canonical pair when the current request is not in history", () => {
    const result = convert(input({ current_state: envelope() }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-a",
      "assistant:request-a",
    ]);
    expect(text(assistant(result.messages))).toBe("实时正文");
  });

  it("reconciles a saved current request with history without duplicating either message", () => {
    const history = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "旧快照" },
    ]);
    const saved = envelope({
      turn_index: 0,
      run: runState({
        status: "completed",
        answer: { attempt_id: "attempt-primary", kind: "primary", text: "最终回答", status: "ready" },
        persistence: "saved",
      }),
    });
    const result = convert(input({ history: { session_id: "session-a", messages: history }, current_state: saved }));

    expect(result.messages).toHaveLength(2);
    expect(text(assistant(result.messages))).toBe("最终回答");
    expect(assistant(result.messages).status.type).toBe("complete");
  });

  it("lets a current saving state override stale history persistence metadata", () => {
    const history = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "已保存快照" },
    ]);
    const saving = envelope({ run: runState({
      status: "completed",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "待保存正文", status: "ready" },
      persistence: "saving",
    }) });
    const result = convert(input({ history: { session_id: "session-a", messages: history }, current_state: saving }));

    expect(productMetadata(assistant(result.messages)).persistence).toBe("saving");
    expect(productMetadata(assistant(result.messages)).run?.persistence).toBe("saving");
  });

  it("retains consecutive requests rather than replacing earlier turns", () => {
    const history = historyMessages([
      { request_id: "request-1", user_query: "第一问", summary: "第一答" },
    ]);
    const current = envelope({
      request_id: "request-2",
      user_message: { id: "user:request-2", text: "第二问" },
      run: runState({ request_id: "request-2", assistant_message_id: "assistant:request-2" }),
    });
    const result = convert(input({ history: { session_id: "session-a", messages: history }, current_state: current }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-1",
      "assistant:request-1",
      "user:request-2",
      "assistant:request-2",
    ]);
  });

  it("maps each streaming snapshot directly without accumulating prior text", () => {
    const previous = convert(input({ current_state: envelope() }));
    const next = envelope({ run: runState({ answer: {
      attempt_id: "attempt-primary",
      kind: "primary",
      text: "实时正文增加",
      status: "streaming",
    } }) });
    const result = convert(input({ history: { session_id: "session-a", messages: previous.messages }, current_state: next }));

    expect(text(assistant(result.messages))).toBe("实时正文增加");
    expect(result.messages).toHaveLength(2);
  });

  it("clears primary text when a fallback snapshot starts with empty text", () => {
    const primary = envelope();
    const degraded = envelope({ run: runState({ answer: {
      attempt_id: "attempt-degraded",
      kind: "degraded",
      text: "",
      status: "pending",
    } }) });
    const first = convert(input({ current_state: primary }));
    const second = convert(input({ history: { session_id: "session-a", messages: first.messages }, current_state: degraded }));

    expect(assistant(second.messages).id).toBe("assistant:request-a");
    expect(text(assistant(second.messages))).toBe("");
    expect(productMetadata(assistant(second.messages)).run?.answer).toMatchObject({
      attempt_id: "attempt-degraded",
      kind: "degraded",
    });
  });

  it("replaces streamed text with canonical final text instead of appending it", () => {
    const partial = envelope();
    const final = envelope({ run: runState({
      status: "completed",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "完整 canonical 回答", status: "ready" },
      persistence: "saving",
    }) });
    const first = convert(input({ current_state: partial }));
    const second = convert(input({ history: { session_id: "session-a", messages: first.messages }, current_state: final }));

    expect(text(assistant(second.messages))).toBe("完整 canonical 回答");
    expect(text(assistant(second.messages))).not.toContain("实时正文");
    expect(second.isRunning).toBe(true);
  });

  it("keeps the completed answer and structured persistence error without duplicating its body in metadata", () => {
    const current = envelope({ run: runState({
      status: "completed",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "保留的正文", status: "ready" },
      persistence: "failed",
      error: { scope: "persistence", code: "chat_store_error", message: "保存结果未确认" },
    }) });
    const result = convert(input({ current_state: current }));
    const message = assistant(result.messages);
    const metadata = productMetadata(message);

    expect(text(message)).toBe("保留的正文");
    expect(metadata.run?.persistence).toBe("failed");
    expect(metadata.run?.error).toEqual({ scope: "persistence", code: "chat_store_error", message: "保存结果未确认" });
    expect(metadata.run?.answer).not.toHaveProperty("text");
    expect(message.status.type).toBe("complete");
  });

  it("lets the current unsaved answer override an older history snapshot", () => {
    const old = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "历史旧正文" },
    ]);
    const current = envelope({ run: runState({ answer: {
      attempt_id: "attempt-primary",
      kind: "primary",
      text: "当前未保存正文",
      status: "streaming",
    } }) });
    const result = convert(input({ history: { session_id: "session-a", messages: old }, current_state: current }));

    expect(text(assistant(result.messages))).toBe("当前未保存正文");
    expect(result.messages[0]?.id).toBe("user:request-a");
  });

  it("reconciles a pending user with its server-confirmed request identity", () => {
    const result = convert(input({ pending_user: pendingUser(), current_state: envelope() }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-a",
      "assistant:request-a",
    ]);
    expect(text(result.messages[0]!)).toBe("同一句问题");
    expect(result.messages[0]?.metadata.isOptimistic).toBe(false);
  });

  it("does not resurrect an optimistic request already confirmed by saved history", () => {
    const history = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "已经保存" },
    ]);
    const result = convert(input({
      history: { session_id: "session-a", messages: history },
      pending_user: pendingUser(),
    }));

    expect(result.messages).toHaveLength(2);
    expect(result.isRunning).toBe(false);
    expect(text(assistant(result.messages))).toBe("已经保存");
  });

  it("keeps identical query text distinct for different request IDs", () => {
    const history = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "第一答" },
    ]);
    const result = convert(input({
      history: { session_id: "session-a", messages: history },
      pending_user: pendingUser({ request_id: "request-b" }),
    }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-a",
      "assistant:request-a",
      "user:request-b",
      "assistant:request-b",
    ]);
    expect(text(assistant(result.messages, "request-a"))).toBe("第一答");
    expect(text(assistant(result.messages, "request-b"))).toBe("");
  });

  it("keeps a saved request A complete while pending request B starts", () => {
    const currentA = envelope({
      user_message: { id: "user:request-a", text: "第一问" },
      run: runState({
        status: "completed",
        answer: { attempt_id: "attempt-primary", kind: "primary", text: "第一答", status: "ready" },
        persistence: "saved",
      }),
    });
    const pendingB = pendingUser({
      request_id: "request-b",
      user_query: "第二问",
      created_at: "2026-09-25T03:00:00.000Z",
    });
    const result = convert(input({
      current_state: currentA,
      pending_user: pendingB,
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-a",
      "assistant:request-a",
      "user:request-b",
      "assistant:request-b",
    ]);
    expect(assistant(result.messages, "request-a").status.type).toBe("complete");
    expect(text(assistant(result.messages, "request-a"))).toBe("第一答");
    expect(assistant(result.messages, "request-b").status.type).toBe("running");
    expect(result.isRunning).toBe(true);
  });

  it("does not let request A failure block pending request B", () => {
    const failedA = envelope({
      user_message: { id: "user:request-a", text: "第一问" },
      run: runState({
        status: "failed",
        answer: { attempt_id: null, kind: null, text: "", status: "interrupted" },
        error: { scope: "execution", code: "runtime_error", message: "运行失败" },
      }),
    });
    const pendingB = pendingUser({ request_id: "request-b", user_query: "第二问" });
    const result = convert(input({
      current_state: failedA,
      pending_user: pendingB,
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(assistant(result.messages, "request-a").status).toEqual({ type: "incomplete", reason: "error" });
    expect(assistant(result.messages, "request-b").status.type).toBe("running");
    expect(result.isRunning).toBe(true);
  });

  it("keeps request A's persistence failure and body while request B runs", () => {
    const failedSaveA = envelope({
      user_message: { id: "user:request-a", text: "第一问" },
      run: runState({
        status: "completed",
        answer: { attempt_id: "attempt-primary", kind: "primary", text: "第一答保留", status: "ready" },
        persistence: "failed",
        error: { scope: "persistence", code: "chat_store_error", message: "保存未确认" },
      }),
    });
    const pendingB = pendingUser({ request_id: "request-b", user_query: "第二问" });
    const result = convert(input({
      current_state: failedSaveA,
      pending_user: pendingB,
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(assistant(result.messages, "request-a").status.type).toBe("complete");
    expect(text(assistant(result.messages, "request-a"))).toBe("第一答保留");
    expect(productMetadata(assistant(result.messages, "request-a")).run?.error?.code)
      .toBe("chat_store_error");
    expect(assistant(result.messages, "request-b").status.type).toBe("running");
    expect(result.isRunning).toBe(true);
  });

  it("settles failed pending request B without interrupting completed request A", () => {
    const savedA = envelope({
      user_message: { id: "user:request-a", text: "第一问" },
      run: runState({
        status: "completed",
        answer: { attempt_id: "attempt-primary", kind: "primary", text: "第一答", status: "ready" },
        persistence: "saved",
      }),
    });
    const pendingB = pendingUser({ request_id: "request-b", user_query: "第二问" });
    const result = convert(input({
      current_state: savedA,
      pending_user: pendingB,
      connection: { request_id: "request-b", status: "error" },
    }));

    expect(assistant(result.messages, "request-a").status.type).toBe("complete");
    expect(productMetadata(assistant(result.messages, "request-a")).connection_status).toBeUndefined();
    expect(assistant(result.messages, "request-b").status).toEqual({ type: "incomplete", reason: "error" });
    expect(productMetadata(assistant(result.messages, "request-b")).connection_status).toBe("error");
    expect(result.isRunning).toBe(false);
  });

  it("reconciles request B's first server snapshot and keeps B's connection status", () => {
    const historyA = historyMessages([
      { request_id: "request-a", user_query: "第一问", summary: "第一答" },
    ]);
    const pendingB = pendingUser({ request_id: "request-b", user_query: "第二问" });
    const currentB = envelope({
      request_id: "request-b",
      user_message: { id: "user:request-b", text: "第二问" },
      run: runState({ answer: {
        attempt_id: "attempt-primary",
        kind: "primary",
        text: "第二答正在生成",
        status: "streaming",
      } }),
    });
    const result = convert(input({
      history: { session_id: "session-a", messages: historyA },
      pending_user: pendingB,
      current_state: currentB,
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(result.messages.map((message) => message.id)).toEqual([
      "user:request-a",
      "assistant:request-a",
      "user:request-b",
      "assistant:request-b",
    ]);
    expect(text(userMessage(result.messages, "request-b"))).toBe("第二问");
    expect(text(assistant(result.messages, "request-b"))).toBe("第二答正在生成");
    expect(productMetadata(assistant(result.messages, "request-b")).connection_status).toBe("sending");
    expect(result.isRunning).toBe(true);
  });

  it.each(["ended", "error"] as const)(
    "ignores late request A connection status %s while request B is current",
    (status) => {
      const historyA = historyMessages([
        { request_id: "request-a", user_query: "第一问", summary: "第一答" },
      ]);
      const currentB = envelope({
        request_id: "request-b",
        user_message: { id: "user:request-b", text: "第二问" },
        run: runState({
          request_id: "request-b",
          answer: { attempt_id: "attempt-primary", kind: "primary", text: "第二答", status: "streaming" },
        }),
      });
      const result = convert(input({
        history: { session_id: "session-a", messages: historyA },
        current_state: currentB,
        connection: { request_id: "request-a", status },
      }));

      expect(assistant(result.messages, "request-b").status.type).toBe("running");
      expect(productMetadata(assistant(result.messages, "request-b")).connection_status).toBeUndefined();
      expect(result.isRunning).toBe(true);
    },
  );

  it("keeps request A's timestamp separate from pending request B", () => {
    const currentA = envelope({ user_message: { id: "user:request-a", text: "第一问" } });
    const pendingB = pendingUser({
      request_id: "request-b",
      user_query: "第二问",
      created_at: "2026-09-25T03:00:00.000Z",
    });
    const currentATime = "2026-09-25T02:00:00.000Z";
    const result = convert(input({
      current_state: currentA,
      pending_user: pendingB,
      current_message_created_at: currentATime,
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(userMessage(result.messages, "request-a").createdAt.toISOString()).toBe(currentATime);
    expect(assistant(result.messages, "request-a").createdAt.toISOString()).toBe(currentATime);
    expect(userMessage(result.messages, "request-b").createdAt.toISOString())
      .toBe("2026-09-25T03:00:00.000Z");
    expect(assistant(result.messages, "request-b").createdAt.toISOString())
      .toBe("2026-09-25T03:00:00.000Z");
  });

  it("preserves an existing historical message timestamp during reconciliation", () => {
    const historyA = historyMessages([
      { request_id: "request-a", user_query: "第一问", summary: "第一答" },
    ]);
    const currentA = envelope({ user_message: { id: "user:request-a", text: "第一问" } });
    const pendingB = pendingUser({
      request_id: "request-b",
      user_query: "第二问",
      created_at: "2026-09-25T03:00:00.000Z",
    });
    const result = convert(input({
      history: { session_id: "session-a", messages: historyA },
      current_state: currentA,
      pending_user: pendingB,
      current_message_created_at: "2026-09-25T02:00:00.000Z",
      connection: { request_id: "request-b", status: "sending" },
    }));

    expect(userMessage(result.messages, "request-a").createdAt.toISOString())
      .toBe("2026-09-24T12:00:00.000Z");
    expect(assistant(result.messages, "request-a").createdAt.toISOString())
      .toBe("2026-09-24T12:00:00.000Z");
  });

  it("rejects a current envelope from a different session", () => {
    expect(() => convert(input({ current_state: envelope({ session_id: "other-session" }) })))
      .toThrow("different session");
  });

  it("settles local busy state after an unexpected end and retains partial text", () => {
    const result = convert(input({
      current_state: envelope(),
      connection: { request_id: "request-a", status: "ended" },
    }));
    const message = assistant(result.messages);

    expect(text(message)).toBe("实时正文");
    expect(message.status).toEqual({ type: "incomplete", reason: "other" });
    expect(productMetadata(message).connection_status).toBe("ended");
    expect(result.isRunning).toBe(false);
  });

  it("retains a ready answer after disconnection without claiming persistence succeeded", () => {
    const current = envelope({ run: runState({
      status: "completed",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "已生成但未确认保存", status: "ready" },
      persistence: "pending",
    }) });
    const result = convert(input({
      current_state: current,
      connection: { request_id: "request-a", status: "ended" },
    }));

    expect(text(assistant(result.messages))).toBe("已生成但未确认保存");
    expect(productMetadata(assistant(result.messages)).run?.persistence).toBe("pending");
    expect(productMetadata(assistant(result.messages)).persistence).toBe("pending");
    expect(result.isRunning).toBe(false);
  });

  it("keeps saved completion normal when the transport reaches EOF", () => {
    const current = envelope({ run: runState({
      status: "completed",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "已保存", status: "ready" },
      persistence: "saved",
    }) });
    const result = convert(input({
      current_state: current,
      connection: { request_id: "request-a", status: "ended" },
    }));

    expect(assistant(result.messages).status.type).toBe("complete");
    expect(productMetadata(assistant(result.messages)).run?.persistence).toBe("saved");
    expect(result.isRunning).toBe(false);
  });

  it("maps cancellation onto the existing request without creating another message or attempt", () => {
    const cancelled = envelope({ run: runState({
      status: "cancelled",
      answer: { attempt_id: "attempt-primary", kind: "primary", text: "已收到的部分", status: "interrupted" },
      persistence: "pending",
    }) });
    const result = convert(input({
      current_state: cancelled,
      connection: { request_id: "request-a", status: "cancelled" },
    }));

    expect(result.messages).toHaveLength(2);
    expect(assistant(result.messages).id).toBe("assistant:request-a");
    expect(text(assistant(result.messages))).toBe("已收到的部分");
    expect(assistant(result.messages).status).toEqual({ type: "incomplete", reason: "cancelled" });
    expect(result.isRunning).toBe(false);
  });

  it("does not invent activity for historical messages", () => {
    const messages = historyMessages([
      { request_id: "request-a", user_query: "问题", summary: "历史回答" },
    ]);
    const result = convert(input({ history: { session_id: "session-a", messages } }));
    const metadata = productMetadata(assistant(result.messages));

    expect(metadata.source).toBe("history");
    expect(metadata.run).toBeUndefined();
    expect(metadata.persistence).toBe("saved");
  });

  it("preserves an existing trace reference when a later snapshot omits it", () => {
    const historical = historyMessages([
      { request_id: "request-a", user_query: "同一句问题", summary: "旧正文" },
    ]);
    const oldAssistant = assistant(historical);
    const trace = { trace_id: "trace-123", expires_at: "2026-10-01T00:00:00Z" };
    const withTrace: ThreadMessage[] = [
      historical[0]!,
      {
        ...oldAssistant,
        metadata: {
          ...oldAssistant.metadata,
          custom: {
            ...oldAssistant.metadata.custom,
            dotamind: {
              request_id: "request-a",
              source: "history",
              persistence: "saved",
              trace,
            } satisfies DotamindMessageMetadata,
          },
        },
      },
    ];
    const result = convert(input({
      history: { session_id: "session-a", messages: withTrace },
      current_state: envelope(),
    }));

    expect(productMetadata(assistant(result.messages)).trace).toEqual(trace);
  });

  it("keeps Markdown image, code block, and link syntax byte-for-byte", () => {
    const markdown = "![图](https://example.test/a.png)\n\n```ts\nconst x = 1;\n```\n\n[链接](https://example.test)";
    const messages = transcriptTurnsToCanonicalMessages([
      { request_id: "request-a", user_query: "保留 ![x](x)", created_at: "2026-09-24T12:00:00Z" },
    ], () => markdown);

    expect(text(messages[0]!)).toBe("保留 ![x](x)");
    expect(text(messages[1]!)).toBe(markdown);
  });

  it("does not mutate input arrays, state, or nested metadata", () => {
    const trace = { trace_id: "trace-before", expires_at: "2026-10-01T00:00:00Z" };
    const current = envelope({ trace, run: runState({ activity: [
      { kind: "tool", id: "activity-1", tool_name: "game.detail", status: "completed", duration_seconds: 0.2, error_code: null },
    ] }) });
    const value = input({ current_state: current });
    const before = structuredClone(value);

    convert(value);

    expect(value).toEqual(before);
    expect(value.current_state?.trace).toBe(trace);
  });

  it("shows a sent request as running before the server's first snapshot", () => {
    const result = convert(
      input({
        pending_user: pendingUser(),
        connection: { request_id: "request-a", status: "sending" },
      }),
      { pendingCommands: [pendingCommand], isSending: true, toolStatuses: {} },
    );

    expect(result.isRunning).toBe(true);
    expect(assistant(result.messages).status.type).toBe("running");
  });

  it("does not stay running after an explicit server failure", () => {
    const current = envelope({ run: runState({
      status: "failed",
      answer: { attempt_id: null, kind: null, text: "", status: "interrupted" },
      error: { scope: "execution", code: "runtime_error", message: "运行失败" },
    }) });
    const result = convert(input({ current_state: current }), {
      pendingCommands: [],
      isSending: true,
      toolStatuses: {},
    });

    expect(assistant(result.messages).status).toEqual({ type: "incomplete", reason: "error" });
    expect(result.isRunning).toBe(false);
  });

  it("rejects an optimistic message whose command text conflicts with the supplied query", () => {
    expect(() => convert(input({
      pending_user: pendingUser({ user_query: "不同文本", command: pendingCommand }),
    })))
      .toThrow("does not match");
  });

  it("settles local busy state after a connection error without changing server Run State", () => {
    const current = envelope();
    const result = convert(input({
      current_state: current,
      connection: { request_id: "request-a", status: "error" },
    }));

    expect(result.isRunning).toBe(false);
    expect(productMetadata(assistant(result.messages)).run?.status).toBe("running");
    expect(productMetadata(assistant(result.messages)).connection_status).toBe("error");
    expect(assistant(result.messages).status).toEqual({ type: "incomplete", reason: "error" });
  });
});
