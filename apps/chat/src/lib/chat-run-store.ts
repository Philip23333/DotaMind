import type { ChatRunStatus, ChatRunSummary } from "./dotamind-api";
import type { ChatRunStreamItem } from "./chat-run-api";

export type ChatRunPhase = "planning" | "tool_execution" | "answering" | "reviewing";

export type ChatRunToolState = {
  toolCallId: string;
  tool: string;
  status: "running" | "ok" | "error";
  latencyMs: number | null;
  failureCode: string | null;
};

export type ChatRunUiState = {
  summary: ChatRunSummary;
  phase: ChatRunPhase | null;
  toolsByCallId: Record<string, ChatRunToolState>;
  provisionalAnswer: string;
  result: Record<string, unknown> | null;
  errorCode: string | null;
  lastEventSequence: number;
};

export type ChatRunStoreState = {
  runsById: Record<string, ChatRunUiState>;
  activeRunIdBySession: Record<string, string | undefined>;
};

export type ChatRunStoreAction =
  | { type: "register"; summary: ChatRunSummary }
  | { type: "event"; item: ChatRunStreamItem }
  | { type: "remove"; runId: string }
  | { type: "clear_session"; sessionId: string };

export const EMPTY_CHAT_RUN_STORE: ChatRunStoreState = {
  runsById: {},
  activeRunIdBySession: {},
};

const ACTIVE_STATUSES: ReadonlySet<ChatRunStatus> = new Set([
  "queued",
  "running",
  "cancel_requested",
]);

function uiState(summary: ChatRunSummary): ChatRunUiState {
  return {
    summary,
    phase: null,
    toolsByCallId: {},
    provisionalAnswer: "",
    result: null,
    errorCode: summary.error_code,
    lastEventSequence: summary.last_event_sequence,
  };
}

function withActiveIndex(state: ChatRunStoreState, run: ChatRunUiState): ChatRunStoreState {
  const active = { ...state.activeRunIdBySession };
  if (ACTIVE_STATUSES.has(run.summary.status)) active[run.summary.session_id] = run.summary.run_id;
  else if (active[run.summary.session_id] === run.summary.run_id) delete active[run.summary.session_id];
  return { ...state, activeRunIdBySession: active };
}

export function chatRunReducer(state: ChatRunStoreState, action: ChatRunStoreAction): ChatRunStoreState {
  if (action.type === "register") {
    const previous = state.runsById[action.summary.run_id];
    const next = previous
      ? { ...previous, summary: action.summary, errorCode: action.summary.error_code }
      : uiState(action.summary);
    return withActiveIndex(
      { ...state, runsById: { ...state.runsById, [action.summary.run_id]: next } },
      next,
    );
  }
  if (action.type === "remove") {
    const run = state.runsById[action.runId];
    if (!run) return state;
    const runs = { ...state.runsById };
    delete runs[action.runId];
    const active = { ...state.activeRunIdBySession };
    if (active[run.summary.session_id] === action.runId) delete active[run.summary.session_id];
    return { runsById: runs, activeRunIdBySession: active };
  }
  if (action.type === "clear_session") {
    const runs = Object.fromEntries(
      Object.entries(state.runsById).filter(([, run]) => run.summary.session_id !== action.sessionId),
    );
    const active = { ...state.activeRunIdBySession };
    delete active[action.sessionId];
    return { runsById: runs, activeRunIdBySession: active };
  }

  const item = action.item;
  if (!("sequence" in item) && item.type === "heartbeat") {
    const run = state.runsById[item.run_id];
    if (!run || run.summary.session_id !== item.session_id || item.last_event_sequence < run.lastEventSequence) {
      return state;
    }
    const next = {
      ...run,
      summary: { ...run.summary, status: item.status, last_event_sequence: item.last_event_sequence },
      lastEventSequence: item.last_event_sequence,
    };
    return withActiveIndex({ ...state, runsById: { ...state.runsById, [item.run_id]: next } }, next);
  }
  if (!("sequence" in item) && item.type === "error") {
    const run = state.runsById[item.run_id];
    if (!run || run.summary.session_id !== item.session_id) return state;
    return { ...state, runsById: { ...state.runsById, [item.run_id]: { ...run, errorCode: item.error_code } } };
  }

  if (!("sequence" in item)) return state;

  const run = state.runsById[item.run_id];
  if (!run || run.summary.session_id !== item.session_id || item.sequence <= run.lastEventSequence) return state;
  const event = item.event;
  const next: ChatRunUiState = {
    ...run,
    lastEventSequence: item.sequence,
    summary: { ...run.summary, last_event_sequence: item.sequence },
  };
  if (event.type === "phase") next.phase = event.phase;
  if (event.type === "tool") {
    next.toolsByCallId = {
      ...run.toolsByCallId,
      [event.tool_call_id]: {
        toolCallId: event.tool_call_id,
        tool: event.tool,
        status: event.status,
        latencyMs: event.latency_ms,
        failureCode: event.failure_code,
      },
    };
  }
  if (event.type === "answer_delta") next.provisionalAnswer = run.provisionalAnswer + event.delta;
  if (event.type === "result") next.result = event.response as Record<string, unknown>;
  if (event.type === "status") {
    next.summary = { ...next.summary, status: event.status, error_code: event.error_code ?? null };
    next.errorCode = event.error_code ?? null;
  }
  return withActiveIndex({ ...state, runsById: { ...state.runsById, [item.run_id]: next } }, next);
}
