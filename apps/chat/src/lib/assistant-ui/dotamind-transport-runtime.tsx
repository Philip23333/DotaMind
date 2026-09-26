"use client";

import {
  useAssistantTransportRuntime,
  useAuiState,
  type AssistantTransportCommand,
  type AssistantTransportConnectionMetadata,
} from "@assistant-ui/react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { getApiUrl, getChatSession, transcriptToInitialMessages } from "@/lib/dotamind-api";
import { markDotaMindSessionUnread } from "./thread-unread";
import {
  DotaMindThreadStateRegistry,
  type DotaMindAcceptedRequest,
  type DotaMindThreadState,
  type DotaMindThreadSnapshot,
  type DotaMindUserMessageCommand,
} from "./dotamind-thread-state";
import {
  type DotamindAssistantTransportEnvelope,
} from "./dotamind-run-state";
import {
  convertDotaMindState,
  type DotaMindAssistantTransportState,
  type PendingDotaMindUserMessage,
} from "./dotamind-state-converter";

type TransportRequestBody = {
  commands: AssistantTransportCommand[];
  parentId?: string | null;
  [key: string]: unknown;
};

type TransportErrorParams = { commands: AssistantTransportCommand[] };
type TransportCancelParams = { commands: AssistantTransportCommand[]; error?: Error };

const ThreadStateRegistryContext = createContext<DotaMindThreadStateRegistry | null>(null);

export function DotaMindThreadStateProvider({
  registry,
  children,
}: {
  registry: DotaMindThreadStateRegistry;
  children: ReactNode;
}) {
  useEffect(() => registry.retain(), [registry]);
  return (
    <ThreadStateRegistryContext.Provider value={registry}>
      {children}
    </ThreadStateRegistryContext.Provider>
  );
}

export function useDotaMindThreadState(
  registryOverride?: DotaMindThreadStateRegistry,
): {
  entry: DotaMindThreadState;
  snapshot: DotaMindThreadSnapshot;
} {
  const contextRegistry = useContext(ThreadStateRegistryContext);
  const registry = registryOverride ?? contextRegistry;
  if (!registry) throw new Error("DotaMind thread state is not available outside its runtime provider");
  const threadId = useAuiState((state) => state.threadListItem.id);
  const entry = useMemo(() => registry.get(threadId), [registry, threadId]);
  const snapshot = useSyncExternalStore(entry.subscribe, entry.getSnapshot, entry.getSnapshot);
  return { entry, snapshot };
}

export function useDotaMindTransportThreadRuntime(
  browserId: string,
  registry: DotaMindThreadStateRegistry,
) {
  const { entry, snapshot } = useDotaMindThreadState(registry);
  const threadId = useAuiState((state) => state.threadListItem.id);
  const sessionId = useAuiState((state) => state.threadListItem.remoteId);

  useEffect(() => {
    if (!sessionId) return;
    entry.markSessionRenderCommitted(sessionId);
    void entry.loadHistory(sessionId, async (signal) => {
      const response = await getChatSession(browserId, sessionId, signal);
      return transcriptToInitialMessages(response);
    });
  }, [browserId, entry, sessionId]);

  const converter = useCallback(
    (
      state: DotamindAssistantTransportEnvelope | null,
      connectionMetadata: AssistantTransportConnectionMetadata,
    ): DotaMindAssistantTransportState => {
      const activeSessionId = sessionId ?? snapshot.session_id ?? `local:${threadId}`;
      const accepted = snapshot.accepted_request;
      const command = accepted?.command ?? pendingUserCommand(connectionMetadata);
      const pending = accepted && command && accepted.session_id === activeSessionId
        ? pendingMessage(accepted, command)
        : null;

      return {
        ...convertDotaMindState(
        {
          session_id: activeSessionId,
          history: {
            session_id: activeSessionId,
            messages: snapshot.history_messages,
          },
          current_state: state?.session_id === activeSessionId ? state : null,
          pending_user: pending,
          connection: snapshot.connection,
          current_message_created_at: accepted?.created_at,
        },
        connectionMetadata,
        ),
        state,
      };
    },
    [sessionId, snapshot, threadId],
  );

  const prepareRequest = useCallback((body: TransportRequestBody): Record<string, unknown> => {
    const current = entry.getSnapshot();
    const request = current.accepted_request;
    const activeSessionId = current.session_id;
    if (!request || !activeSessionId || request.session_id !== activeSessionId) {
      throw new Error("The chat session was not prepared for this request.");
    }
    const command = oneTextUserCommand(body.commands);
    entry.setRequestCommand(request.request_id, command);

    // The server owns model/tool configuration. Send only the accepted command,
    // its identities, and the append parent understood by this endpoint.
    return {
      commands: body.commands,
      state: null,
      threadId: activeSessionId,
      ...(body.parentId === undefined ? {} : { parentId: body.parentId }),
      request_id: request.request_id,
    };
  }, [entry]);

  const onFinish = useCallback(() => {
    const request = entry.getSnapshot().accepted_request;
    if (!request) return;
    entry.finishConnection(request.request_id);
  }, [entry]);

  const onError = useCallback((_error: Error, { commands }: TransportErrorParams) => {
    const request = entry.getSnapshot().accepted_request;
    if (!request) return;
    const command = findUserCommand(commands);
    if (command) entry.setRequestCommand(request.request_id, command);
    entry.setConnection(request.request_id, "error");
  }, [entry]);

  const onCancel = useCallback(({ commands, error }: TransportCancelParams) => {
    const request = entry.getSnapshot().accepted_request;
    if (!request) return;
    const command = findUserCommand(commands);
    if (command) entry.setRequestCommand(request.request_id, command);
    entry.setConnection(request.request_id, error ? "error" : "cancelled");
  }, [entry]);

  const api = getTransportSessionUrl(sessionId ?? snapshot.session_id);
  const options = useMemo(
    () => ({
      initialState: null,
      api,
      protocol: "assistant-transport" as const,
      headers: { "X-DotaMind-Browser-Id": browserId },
      converter,
      prepareSendCommandsRequest: prepareRequest,
      onFinish,
      onError,
      onCancel,
      capabilities: { edit: false },
    }),
    [api, browserId, converter, onCancel, onError, onFinish, prepareRequest],
  );
  const runtime = useAssistantTransportRuntime<DotamindAssistantTransportEnvelope | null>(options);
  useEffect(() => {
    const checkCompletion = () => {
      const request = entry.getSnapshot().accepted_request;
      const state = runtime.thread.getState().state;
      if (
        request &&
        isTransportEnvelope(state) &&
        state.session_id === request.session_id &&
        state.request_id === request.request_id &&
        state.run.status === "completed" &&
        entry.markCompletionUnreadOnce(request.request_id)
      ) {
        markDotaMindSessionUnread(request.session_id);
      }
    };
    checkCompletion();
    return runtime.thread.subscribe(checkCompletion);
  }, [entry, runtime]);
  return runtime;
}

export function getTransportSessionUrl(sessionId: string | null): string {
  return `${getApiUrl()}/api/v1/chat/sessions/${encodeURIComponent(sessionId ?? "uninitialized")}/transport`;
}

export function ensurePendingMessage(
  accepted: DotaMindAcceptedRequest | null,
  connectionMetadata: AssistantTransportConnectionMetadata,
): PendingDotaMindUserMessage | null {
  if (!accepted) return null;
  const command = accepted.command ?? pendingUserCommand(connectionMetadata);
  return command ? pendingMessage(accepted, command) : null;
}

function pendingMessage(
  accepted: DotaMindAcceptedRequest,
  command: DotaMindUserMessageCommand,
): PendingDotaMindUserMessage {
  return {
    session_id: accepted.session_id,
    request_id: accepted.request_id,
    user_query: command.message.parts
      .map((part) => (part.type === "text" ? part.text : ""))
      .join(""),
    command,
    created_at: accepted.created_at,
  };
}

function pendingUserCommand(
  metadata: AssistantTransportConnectionMetadata,
): DotaMindUserMessageCommand | null {
  return findUserCommand(metadata.pendingCommands);
}

function findUserCommand(
  commands: readonly AssistantTransportCommand[],
): DotaMindUserMessageCommand | null {
  return commands.find((command) => isTextUserCommand(command) &&
    command.message.parts.every((part) => part.type === "text")) as DotaMindUserMessageCommand | undefined ?? null;
}

function isTextUserCommand(command: AssistantTransportCommand): command is DotaMindUserMessageCommand {
  return command.type === "add-message" && command.message.role === "user";
}

function oneTextUserCommand(
  commands: readonly AssistantTransportCommand[],
): DotaMindUserMessageCommand {
  if (commands.length !== 1 || !isTextUserCommand(commands[0]!)) {
    throw new Error("Only one new user message can be sent for a chat request.");
  }
  const command = commands[0];
  if (!command || command.sourceId !== null || command.message.parts.some((part) => part.type !== "text")) {
    throw new Error("Only new text messages are supported.");
  }
  const text = command.message.parts
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("");
  if (!text.trim()) throw new Error("A chat request must contain text.");
  return command;
}

function isTransportEnvelope(value: unknown): value is DotamindAssistantTransportEnvelope {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.session_id === "string" && typeof record.request_id === "string" &&
    typeof record.run === "object" && record.run !== null;
}
