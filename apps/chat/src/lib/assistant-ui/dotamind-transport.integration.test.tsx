// @vitest-environment jsdom
import {
  AssistantTransportEncoder,
  type AssistantStreamChunk,
  type AssistantTransportStateOperation,
} from "assistant-stream";
import {
  useAui,
  useAuiState,
  type ThreadMessage,
} from "@assistant-ui/react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Thread } from "@/components/thread";
import { ChatSidebar } from "@/components/chat-sidebar";
import { DotaMindRuntimeProvider } from "./runtime-provider";
import { DotaMindThreadState } from "./dotamind-thread-state";
import {
  getSessionUnreadCount,
  markDotaMindSessionRead,
  markDotaMindSessionUnread,
  useActiveSessionReadState,
} from "./thread-unread";

type Session = {
  session_id: string;
  game: "dota2";
  title: string;
  title_is_custom: boolean;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
  active_run: null;
};

type TransportRequest = {
  sessionId: string;
  requestId: string;
  text: string;
  body: Record<string, unknown>;
  signal: AbortSignal;
  responseText: string;
  closed: boolean;
  send: (chunk: AssistantStreamChunk) => void;
  close: () => void;
  fail: () => void;
};

class ControlledBackend {
  readonly calls: Array<{ url: string; method: string; headers: Headers; body?: Record<string, unknown> }> = [];
  readonly requests: TransportRequest[] = [];
  readonly sessions = new Map<string, Session>();
  failCreate = false;
  failNextTransport = false;
  nextId = 1;

  constructor(initialSessions: string[] = ["session-a", "session-b"]) {
    for (const id of initialSessions) this.sessions.set(id, makeSession(id));
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : undefined;
    this.calls.push({ url: url.toString(), method, headers, ...(body ? { body } : {}) });

    if (url.pathname === "/api/v1/chat/sessions" && method === "GET") {
      return json({ sessions: [...this.sessions.values()] });
    }
    if (url.pathname === "/api/v1/chat/sessions" && method === "POST") {
      if (this.failCreate) return json({ reason: "private create failure" }, 503);
      const session = makeSession(`created-${this.nextId++}`);
      this.sessions.set(session.session_id, session);
      return json(session);
    }

    const transportMatch = url.pathname.match(/^\/api\/v1\/chat\/sessions\/([^/]+)\/transport$/);
    if (transportMatch && method === "POST") {
      const sessionId = decodeURIComponent(transportMatch[1]!);
      if (this.failNextTransport) {
        this.failNextTransport = false;
        return json({ detail: "private transport failure" }, 503);
      }
      if (!body) return json({ detail: "missing body" }, 400);
      const commands = body.commands as Array<{ type: string; message?: { parts?: Array<{ type: string; text?: string }> } }>;
      const text = commands?.[0]?.message?.parts?.map((part) => part.text ?? "").join("") ?? "";
      const requestId = String(body.request_id ?? "");
      let streamController: ReadableStreamDefaultController<AssistantStreamChunk> | null = null;
      const source = new ReadableStream<AssistantStreamChunk>({
        start(controller) {
          streamController = controller;
        },
      });
      const encoder = new AssistantTransportEncoder();
      const signal = init?.signal ?? new AbortController().signal;
      const request: TransportRequest = {
        sessionId,
        requestId,
        text,
        body,
        signal,
        responseText: "",
        closed: false,
        send: (chunk) => {
          if (!request.closed) streamController?.enqueue(chunk);
        },
        close: () => {
          if (request.closed) return;
          request.closed = true;
          streamController?.close();
        },
        fail: () => {
          if (request.closed) return;
          request.closed = true;
          streamController?.error(new DOMException("request cancelled", "AbortError"));
        },
      };
      signal.addEventListener("abort", request.fail, { once: true });
      this.requests.push(request);
      return new Response(source.pipeThrough(encoder), { headers: encoder.headers });
    }

    const sessionMatch = url.pathname.match(/^\/api\/v1\/chat\/sessions\/([^/]+)$/);
    if (sessionMatch && method === "GET") {
      const sessionId = decodeURIComponent(sessionMatch[1]!);
      const session = this.sessions.get(sessionId);
      return session
        ? json({ session, turns: [] })
        : json({ detail: "not found" }, 404);
    }
    return json({ detail: "not found" }, 404);
  };
}

function makeSession(id: string): Session {
  const now = "2026-09-25T00:00:00.000Z";
  return {
    session_id: id,
    game: "dota2",
    title: id,
    title_is_custom: false,
    is_pinned: false,
    created_at: now,
    updated_at: now,
    active_run: null,
  };
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function TestThreadSelectors() {
  const aui = useAui();
  const activeSessionId = useAuiState((state) => state.threadListItem.remoteId);
  useActiveSessionReadState(activeSessionId);
  return (
    <ChatSidebar
      onNew={() => aui.threads.switchToNewThread()}
      onRename={async () => undefined}
      onPin={async () => undefined}
      onDelete={async () => undefined}
    />
  );
}

function TestChat({ browserId = "browser-test" }: { browserId?: string }) {
  return (
    <DotaMindRuntimeProvider browserId={browserId}>
      <TestThreadSelectors />
      <div className="h-screen">
        <Thread browserId={browserId} />
      </div>
    </DotaMindRuntimeProvider>
  );
}

function rootEnvelope(request: TransportRequest, text = "") {
  return {
    session_id: request.sessionId,
    request_id: request.requestId,
    user_message: { id: `user:${request.requestId}`, text: request.text },
    run: {
      request_id: request.requestId,
      assistant_message_id: `assistant:${request.requestId}`,
      status: "running",
      stage: "answer",
      activity: [],
      omitted_activity_count: 0,
      answer: { attempt_id: "primary", kind: "primary", text, status: text ? "streaming" : "pending" },
      persistence: "pending",
      error: null,
    },
    turn_index: null,
    trace: null,
  };
}

function update(request: TransportRequest, operations: AssistantTransportStateOperation[]) {
  request.send({ type: "update-state", path: [], operations });
}

function startRun(request: TransportRequest) {
  update(request, [{ type: "set", path: [], value: rootEnvelope(request) }]);
}

function append(request: TransportRequest, text: string) {
  request.responseText += text;
  update(request, [{ type: "append-text", path: ["run", "answer", "text"], value: text }]);
}

function fallback(request: TransportRequest, text: string) {
  request.responseText = text;
  update(request, [{
    type: "set",
    path: ["run", "answer"],
    value: { attempt_id: "fallback", kind: "degraded", text, status: text ? "streaming" : "pending" },
  }]);
}

function complete(request: TransportRequest, finalText?: string) {
  if (finalText !== undefined) {
    fallback(request, finalText);
  }
  update(request, [{
    type: "set",
    path: ["run"],
    value: {
      ...rootEnvelope(request).run,
      status: "completed",
      answer: {
        attempt_id: finalText === undefined ? "primary" : "fallback",
        kind: finalText === undefined ? "primary" : "degraded",
        text: request.responseText,
        status: "ready",
      },
      persistence: "saved",
      error: null,
    },
  }]);
  request.close();
}

function completeWhileSaving(request: TransportRequest) {
  update(request, [{
    type: "set",
    path: ["run"],
    value: {
      ...rootEnvelope(request).run,
      status: "completed",
      answer: {
        attempt_id: "primary",
        kind: "primary",
        text: request.responseText,
        status: "ready",
      },
      persistence: "saving",
      error: null,
    },
  }]);
}

function finishSaving(request: TransportRequest) {
  update(request, [{ type: "set", path: ["run", "persistence"], value: "saved" }]);
  request.close();
}

async function waitForRequest(backend: ControlledBackend, count: number): Promise<TransportRequest> {
  await waitFor(() => expect(backend.requests).toHaveLength(count));
  return backend.requests[count - 1]!;
}

async function selectSession(id: string) {
  await screen.findByTestId(`switch-${id}`);
  fireEvent.click(screen.getByTestId(`switch-${id}`));
  await waitFor(() => {
    expect(screen.getByTestId(`switch-${id}`).parentElement?.getAttribute("aria-current")).toBe("true");
  });
}

async function submit(text: string) {
  const input = screen.getByRole("textbox", { name: "消息输入框" });
  fireEvent.change(input, { target: { value: text } });
  await waitFor(() => {
    const button = screen.getByRole("button", { name: "发送消息" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
}

function chatView() {
  return within(document.querySelector(".chat-main-surface")!);
}

function chatText(): string {
  return document.querySelector(".chat-main-surface")?.textContent ?? "";
}

function assistantMessage(id: string, text: string): ThreadMessage {
  return {
    id,
    role: "assistant",
    content: [{ type: "text", text }],
    createdAt: new Date("2026-09-25T00:00:00.000Z"),
    status: { type: "complete", reason: "stop" },
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: {},
    },
  };
}

function installBackend(backend: ControlledBackend) {
  vi.stubGlobal("fetch", vi.fn(backend.fetch));
}

let backend: ControlledBackend;

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: () => undefined,
  });
  backend = new ControlledBackend();
  installBackend(backend);
});

afterEach(() => {
  for (const request of backend.requests) {
    if (!request.signal.aborted) request.close();
  }
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("normal AssistantTransport chat integration", () => {
  it("sends once to the matching session with one request ID and streams before the response ends", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("A question");
    const request = await waitForRequest(backend, 1);

    expect(request.sessionId).toBe("session-a");
    expect(request.body.threadId).toBe("session-a");
    expect(request.body.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(request.text).toBe("A question");
    expect(request.signal.aborted).toBe(false);
    expect(backend.requests).toHaveLength(1);
    expect(backend.calls.filter((call) => call.url.includes("/messages"))).toHaveLength(0);
    expect(backend.calls.find((call) => call.url.includes("/transport"))?.headers.get("X-DotaMind-Browser-Id"))
      .toBe("browser-test");
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();

    await act(async () => startRun(request));
    await act(async () => append(request, "first fragment"));
    expect(await chatView().findByText("first fragment")).toBeTruthy();
    expect(request.signal.aborted).toBe(false);
    await act(async () => complete(request));
    expect(await chatView().findByText("first fragment")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "停止生成" })).toBeNull();
  });

  it("replaces a primary fallback answer in place and keeps one canonical assistant message", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("fallback please");
    const request = await waitForRequest(backend, 1);
    await act(async () => startRun(request));
    await act(async () => append(request, "primary fragment"));
    expect(await chatView().findByText("primary fragment")).toBeTruthy();
    await act(async () => fallback(request, ""));
    await act(async () => append(request, "replacement answer"));
    expect(await chatView().findByText("replacement answer")).toBeTruthy();
    expect(chatView().queryByText("primary fragment")).toBeNull();
    expect(chatView().getAllByText("fallback please")).toHaveLength(1);
    await act(async () => complete(request));
    expect(chatView().getAllByText("replacement answer")).toHaveLength(1);
  });

  it("keeps both completed history and the next pending turn in canonical order", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("question A");
    const first = await waitForRequest(backend, 1);
    await act(async () => startRun(first));
    await act(async () => append(first, "answer A"));
    await act(async () => complete(first));
    await submit("question B");
    const second = await waitForRequest(backend, 2);

    expect(second.sessionId).toBe("session-a");
    expect(second.requestId).not.toBe(first.requestId);
    expect(await chatView().findByText("answer A")).toBeTruthy();
    expect(chatView().getAllByText("question A")).toHaveLength(1);
    expect(chatView().getAllByText("question B")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
    await act(async () => startRun(second));
    await act(async () => append(second, "answer B"));
    expect(await chatView().findByText("answer B")).toBeTruthy();
    expect(chatView().getAllByText("answer A")).toHaveLength(1);
    await act(async () => complete(second));
  });

  it("keeps two sessions live while switching and cancels only the selected session", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("question A");
    const a = await waitForRequest(backend, 1);
    await act(async () => startRun(a));
    await act(async () => append(a, "A before switch"));
    expect(await chatView().findByText("A before switch")).toBeTruthy();

    fireEvent.click(screen.getByTestId("switch-session-b"));
    await waitFor(() => expect(a.signal.aborted).toBe(false));
    await submit("question B");
    const b = await waitForRequest(backend, 2);
    expect(b.sessionId).toBe("session-b");
    await act(async () => startRun(b));
    await act(async () => append(a, "A after switch"));
    await act(async () => append(b, "B after switch"));

    fireEvent.click(screen.getByRole("button", { name: "停止生成" }));
    await waitFor(() => expect(b.signal.aborted).toBe(true));
    expect(a.signal.aborted).toBe(false);
    expect(backend.requests).toHaveLength(2);
    expect(await chatView().findByText("B after switch")).toBeTruthy();

    fireEvent.click(screen.getByTestId("switch-session-a"));
    await waitFor(() => {
      expect(screen.getByTestId("switch-session-a").parentElement?.getAttribute("aria-current")).toBe("true");
    });
    expect(chatText()).toContain("A after switch");
    expect(a.signal.aborted).toBe(false);
    await act(async () => complete(a));
  });

  it("stopping A leaves B's stream active and does not issue a replacement request", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("question A");
    const a = await waitForRequest(backend, 1);
    await act(async () => startRun(a));

    await selectSession("session-b");
    await submit("question B");
    const b = await waitForRequest(backend, 2);
    await act(async () => startRun(b));

    await selectSession("session-a");
    fireEvent.click(screen.getByRole("button", { name: "停止生成" }));
    await waitFor(() => expect(a.signal.aborted).toBe(true));
    expect(b.signal.aborted).toBe(false);
    expect(backend.requests).toHaveLength(2);

    await selectSession("session-b");
    await act(async () => append(b, "B still streaming"));
    expect(chatText()).toContain("B still streaming");
    await act(async () => complete(b));
  });

  it("surfaces safe connection errors, allows retry, and keeps server persistence failures visible", async () => {
    backend.failNextTransport = true;
    render(<TestChat />);
    await selectSession("session-a");
    await submit("first request fails before a frame");
    await waitFor(() => expect(backend.calls.some((call) => call.url.includes("/transport"))).toBe(true));
    expect(await screen.findAllByText("连接中断，已保留当前可见内容。")).toHaveLength(1);
    expect(screen.queryByText("private transport failure")).toBeNull();

    await submit("retry as a new request");
    const request = await waitForRequest(backend, 1);
    expect(request.text).toBe("retry as a new request");
    await act(async () => startRun(request));
    await act(async () => append(request, "body retained"));
    update(request, [{
      type: "set",
      path: ["run"],
      value: {
        ...rootEnvelope(request).run,
        status: "completed",
        answer: { attempt_id: "primary", kind: "primary", text: "body retained", status: "ready" },
        persistence: "failed",
        error: { scope: "persistence", code: "chat_store_error", message: "safe" },
      },
    }]);
    request.close();
    expect(await screen.findByText("回答已生成，但未能确认保存结果，请重试保存。")).toBeTruthy();
    expect(screen.getByText("body retained")).toBeTruthy();
    expect(backend.requests).toHaveLength(1);
  });

  it("initializes a new session before transport, deduplicates rapid sends, and clears failed preparation", async () => {
    render(<TestChat />);
    const input = screen.getByRole("textbox", { name: "消息输入框" });
    fireEvent.change(input, { target: { value: "initialize then send" } });
    const form = input.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    fireEvent.submit(form!);
    await waitFor(() => expect(backend.requests).toHaveLength(1));
    const createIndex = backend.calls.findIndex((call) => call.method === "POST" && call.url.endsWith("/sessions"));
    const transportIndex = backend.calls.findIndex((call) => call.url.includes("/transport"));
    expect(createIndex).toBeGreaterThanOrEqual(0);
    expect(createIndex).toBeLessThan(transportIndex);
    expect(backend.calls.filter((call) => call.method === "POST" && call.url.endsWith("/sessions"))).toHaveLength(1);
    expect(backend.requests[0]?.sessionId).toBe("created-1");
    await act(async () => complete(backend.requests[0]!));

    cleanup();
    backend = new ControlledBackend([]);
    backend.failCreate = true;
    installBackend(backend);
    render(<TestChat />);
    await submit("create fails");
    expect(await screen.findByText("无法建立聊天，请重试。")).toBeTruthy();
    expect(backend.requests).toHaveLength(0);
    expect(screen.getByRole("button", { name: "发送消息" })).toBeTruthy();
  });

  it("clears a background completion when selected and does not recreate it on save updates", async () => {
    render(<TestChat />);
    await selectSession("session-a");
    await submit("complete in background");
    const a = await waitForRequest(backend, 1);
    await act(async () => startRun(a));
    await act(async () => append(a, "A answer"));

    await selectSession("session-b");
    await submit("keep B running");
    const b = await waitForRequest(backend, 2);
    await act(async () => startRun(b));

    await act(async () => completeWhileSaving(a));
    await waitFor(() => expect(getSessionUnreadCount("session-a")).toBe(1));
    expect(screen.getByTestId("unread-session-a").textContent).toBe("1");

    await selectSession("session-a");
    expect(getSessionUnreadCount("session-a")).toBe(0);
    expect(screen.queryByTestId("unread-session-a")).toBeNull();
    expect(b.signal.aborted).toBe(false);

    await selectSession("session-b");
    await act(async () => finishSaving(a));
    expect(getSessionUnreadCount("session-a")).toBe(0);
    expect(screen.queryByTestId("unread-session-a")).toBeNull();
    expect(b.signal.aborted).toBe(false);
  });

  it("keeps session unread counts isolated and unload aborts its active transport", async () => {
    const rendered = render(<TestChat />);
    await selectSession("session-a");
    await submit("background completion");
    const request = await waitForRequest(backend, 1);
    await act(async () => startRun(request));
    await selectSession("session-b");
    await act(async () => complete(request));
    expect(getSessionUnreadCount("session-a")).toBe(1);
    expect(screen.getByTestId("unread-session-a").textContent).toBe("1");

    await selectSession("session-a");
    markDotaMindSessionUnread("session-b");
    expect(getSessionUnreadCount("session-a")).toBe(0);
    expect(getSessionUnreadCount("session-b")).toBe(1);

    markDotaMindSessionRead("session-a");
    expect(getSessionUnreadCount("session-a")).toBe(0);
    expect(getSessionUnreadCount("session-b")).toBe(1);

    await selectSession("session-b");
    expect(getSessionUnreadCount("session-b")).toBe(0);
    await submit("unload me");
    const pending = await waitForRequest(backend, 2);
    rendered.unmount();
    await waitFor(() => expect(pending.signal.aborted).toBe(true));
  });
});

describe("per-thread history reconciliation", () => {
  it("merges a delayed history snapshot without replacing a newer visible canonical message", async () => {
    const state = new DotaMindThreadState();
    let resolveHistory!: (messages: readonly ThreadMessage[]) => void;
    const history = new Promise<readonly ThreadMessage[]>((resolve) => {
      resolveHistory = resolve;
    });
    const loading = state.loadHistory("session-a", () => history);
    const currentAnswer = assistantMessage("assistant:request-a", "new visible answer");
    state.captureVisibleMessages([currentAnswer]);

    resolveHistory([
      assistantMessage("assistant:request-a", "stale history answer"),
      assistantMessage("assistant:request-old", "older saved answer"),
    ]);
    await loading;

    const messages = state.getSnapshot().history_messages;
    expect(messages.map((message) => message.id)).toEqual([
      "assistant:request-a",
      "assistant:request-old",
    ]);
    expect(messages[0]?.content).toEqual([{ type: "text", text: "new visible answer" }]);
  });
});
