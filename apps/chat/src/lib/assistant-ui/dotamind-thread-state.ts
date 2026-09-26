import type { AssistantTransportCommand, ThreadMessage } from "@assistant-ui/react";

import type {
  DotamindConnectionStatus,
  DotamindRequestConnection,
} from "./dotamind-run-state";

type DotaMindAddMessageCommand = Extract<AssistantTransportCommand, { type: "add-message" }>;
export type DotaMindUserMessageCommand = Omit<DotaMindAddMessageCommand, "message"> & {
  message: Extract<DotaMindAddMessageCommand["message"], { role: "user" }>;
};

export type DotaMindAcceptedRequest = {
  session_id: string;
  request_id: string;
  created_at: string;
  command: DotaMindUserMessageCommand | null;
};

export type DotaMindThreadSnapshot = {
  session_id: string | null;
  history_messages: readonly ThreadMessage[];
  history_status: "ready" | "loading" | "error";
  accepted_request: DotaMindAcceptedRequest | null;
  connection: DotamindRequestConnection | null;
  is_submitting: boolean;
  notice: "initialization" | "history" | "connection" | null;
};

type HistoryLoader = (signal: AbortSignal) => Promise<readonly ThreadMessage[]>;

/** Per-assistant-ui-thread state. A registry instance lives inside one provider. */
export class DotaMindThreadState {
  private snapshot: DotaMindThreadSnapshot = {
    session_id: null,
    history_messages: [],
    history_status: "ready",
    accepted_request: null,
    connection: null,
    is_submitting: false,
    notice: null,
  };

  private listeners = new Set<() => void>();
  private historyTask: Promise<void> | null = null;
  private historyController: AbortController | null = null;
  private sessionCommitWaiters = new Map<string, Set<(disposed: boolean) => void>>();
  private committedSessionIds = new Set<string>();
  private notifiedCompletions = new Set<string>();
  private disposed = false;

  readonly getSnapshot = (): DotaMindThreadSnapshot => this.snapshot;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private update(patch: Partial<DotaMindThreadSnapshot>): void {
    if (this.disposed) return;
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  markNewSession(sessionId: string): void {
    if (this.snapshot.session_id === sessionId && this.snapshot.history_status === "ready") return;
    this.historyController?.abort();
    this.historyController = null;
    this.historyTask = null;
    this.update({
      session_id: sessionId,
      history_messages: [],
      history_status: "ready",
      notice: null,
    });
  }

  markSessionRenderCommitted(sessionId: string): void {
    this.committedSessionIds.add(sessionId);
    const waiters = this.sessionCommitWaiters.get(sessionId);
    if (!waiters) return;
    this.sessionCommitWaiters.delete(sessionId);
    for (const settle of waiters) settle(false);
  }

  waitForSessionRenderCommit(sessionId: string): Promise<void> {
    if (this.disposed) return Promise.reject(new Error("thread runtime was disposed"));
    if (this.committedSessionIds.has(sessionId)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const waiters = this.sessionCommitWaiters.get(sessionId) ?? new Set<(disposed: boolean) => void>();
      waiters.add((disposed) => {
        if (disposed) reject(new Error("thread runtime was disposed"));
        else resolve();
      });
      this.sessionCommitWaiters.set(sessionId, waiters);
    });
  }

  loadHistory(sessionId: string, loader: HistoryLoader): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (this.snapshot.session_id === sessionId) {
      if (this.snapshot.history_status === "ready") return Promise.resolve();
      if (this.historyTask) return this.historyTask;
    }

    this.historyController?.abort();
    const controller = new AbortController();
    this.historyController = controller;
    this.update({
      session_id: sessionId,
      history_messages: [],
      history_status: "loading",
      notice: null,
    });
    const task = loader(controller.signal)
      .then((messages) => {
        if (controller.signal.aborted || this.historyController !== controller) return;
        const merged = new Map(messages.map((message) => [message.id, message]));
        // A session can accumulate visible messages while an older history
        // snapshot is resolving. Keep the already captured canonical message
        // for matching IDs and append locally retained messages absent upstream.
        for (const message of this.snapshot.history_messages) merged.set(message.id, message);
        this.update({ history_messages: [...merged.values()], history_status: "ready", notice: null });
      })
      .catch(() => {
        if (controller.signal.aborted || this.historyController !== controller) return;
        this.update({ history_status: "error", notice: "history" });
      })
      .finally(() => {
        if (this.historyTask === task) this.historyTask = null;
      });
    this.historyTask = task;
    return task;
  }

  beginSubmission(): boolean {
    if (this.snapshot.is_submitting) return false;
    this.update({ is_submitting: true, notice: null });
    return true;
  }

  finishSubmissionWithError(notice: "initialization" | "history"): void {
    this.update({ is_submitting: false, notice });
  }

  acceptRequest(request: DotaMindAcceptedRequest): void {
    this.update({
      session_id: request.session_id,
      accepted_request: request,
      connection: { request_id: request.request_id, status: "sending" },
      is_submitting: false,
      notice: null,
    });
  }

  setRequestCommand(requestId: string, command: DotaMindUserMessageCommand): void {
    const accepted = this.snapshot.accepted_request;
    if (!accepted || accepted.request_id !== requestId) return;
    this.update({ accepted_request: { ...accepted, command } });
  }

  setConnection(requestId: string, status: DotamindConnectionStatus): void {
    const current = this.snapshot.connection;
    if (!current || current.request_id !== requestId) return;
    if (current.status === "error" && status === "cancelled") return;
    this.update({
      connection: { request_id: requestId, status },
      notice: status === "error" ? "connection" : this.snapshot.notice,
    });
  }

  finishConnection(requestId: string): void {
    if (this.snapshot.connection?.request_id !== requestId) return;
    if (this.snapshot.connection.status === "sending") this.setConnection(requestId, "ended");
  }

  captureVisibleMessages(messages: readonly ThreadMessage[]): void {
    const history = new Map(this.snapshot.history_messages.map((message) => [message.id, message]));
    for (const message of messages) history.set(message.id, message);
    this.update({ history_messages: [...history.values()] });
  }

  markCompletionUnreadOnce(requestId: string): boolean {
    if (this.notifiedCompletions.has(requestId)) return false;
    this.notifiedCompletions.add(requestId);
    return true;
  }

  dispose(): void {
    this.disposed = true;
    this.historyController?.abort();
    this.historyController = null;
    this.historyTask = null;
    for (const waiters of this.sessionCommitWaiters.values()) {
      for (const settle of waiters) settle(true);
    }
    this.sessionCommitWaiters.clear();
    this.listeners.clear();
  }
}

export class DotaMindThreadStateRegistry {
  private entries = new Map<string, DotaMindThreadState>();
  private disposeTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly browserId: string) {}

  retain(): () => void {
    if (this.disposeTimer !== null) {
      clearTimeout(this.disposeTimer);
      this.disposeTimer = null;
    }
    return () => {
      // React Strict Mode replays effect cleanup/setup in development. Deferring
      // disposal one task lets the replay retain this same provider registry.
      this.disposeTimer = setTimeout(() => {
        this.disposeTimer = null;
        this.disposeNow();
      }, 0);
    };
  }

  get(threadId: string): DotaMindThreadState {
    const key = `${this.browserId}:${threadId}`;
    let entry = this.entries.get(key);
    if (!entry) {
      entry = new DotaMindThreadState();
      this.entries.set(key, entry);
    }
    return entry;
  }

  dispose(): void {
    if (this.disposeTimer !== null) {
      clearTimeout(this.disposeTimer);
      this.disposeTimer = null;
    }
    this.disposeNow();
  }

  private disposeNow(): void {
    for (const entry of this.entries.values()) entry.dispose();
    this.entries.clear();
  }
}
