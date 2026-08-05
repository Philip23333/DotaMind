"use client";

import {
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  type ThreadMessageLike,
  useLocalRuntime,
} from "@assistant-ui/react";
import { ChatSidebar } from "@/components/chat-sidebar";
import { Button } from "@/components/ui/button";
import {
  RuntimeInfoProvider,
  type RuntimeInfo,
  type RuntimeInfoMap,
  type RuntimeTool,
} from "@/components/runtime-info";
import { Thread } from "@/components/thread";
import {
  createChatSession,
  deleteChatSession,
  formatPlanResponse,
  formatStreamError,
  getChatSession,
  getOrCreateBrowserId,
  getStoredActiveSessionId,
  latestUserText,
  listChatSessions,
  renameChatSession,
  setChatSessionPinned,
  storeActiveSessionId,
  streamDotaMind,
  transcriptToInitialMessages,
  type ChatSessionSummary,
} from "@/lib/dotamind-api";
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { MenuIcon } from "lucide-react";

const finalRunStatus = (status: string | undefined): RuntimeInfo["status"] =>
  status === "error" || status === "insufficient_evidence" ? "failed" : "completed";

const cancelledMessage = "本次分析已取消。";
const incompleteMessage = "连接在收到最终结果前结束，请重试。";

export const Assistant = () => {
  const [browserId] = useState(() => getOrCreateBrowserId());
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [initialMessages, setInitialMessages] = useState<ThreadMessageLike[]>([]);
  const [runtimeRuns, setRuntimeRuns] = useState<RuntimeInfoMap>({});
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activateSession = useCallback(
    async (sessionId: string) => {
      setLoading(true);
      setError(null);
      setRuntimeRuns({});
      try {
        const session = await getChatSession(browserId, sessionId);
        setInitialMessages(transcriptToInitialMessages(session));
        setActiveSessionId(sessionId);
        storeActiveSessionId(sessionId);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "无法加载聊天记录。");
      } finally {
        setLoading(false);
      }
    },
    [browserId],
  );

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      try {
        let available = await listChatSessions(browserId);
        if (available.length === 0) {
          available = [await createChatSession(browserId)];
        }
        if (cancelled) return;
        setSessions(available);
        const stored = getStoredActiveSessionId();
        const selected =
          (stored && available.some((session) => session.session_id === stored) && stored) ||
          available[0].session_id;
        await activateSession(selected);
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "无法初始化聊天。");
          setLoading(false);
        }
      }
    };
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [activateSession, browserId]);

  const createNewSession = useCallback(async () => {
    setError(null);
    try {
      const created = await createChatSession(browserId);
      setSessions((current) => sortSessions([created, ...current]));
      await activateSession(created.session_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建新聊天。");
    }
  }, [activateSession, browserId]);

  const renameSession = useCallback(
    async (sessionId: string, title: string) => {
      try {
        const renamed = await renameChatSession(browserId, sessionId, title);
        setSessions((current) =>
          current.map((session) => (session.session_id === sessionId ? renamed : session)),
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "无法重命名聊天。");
      }
    },
    [browserId],
  );

  const pinSession = useCallback(
    async (sessionId: string, isPinned: boolean) => {
      try {
        const updated = await setChatSessionPinned(browserId, sessionId, isPinned);
        setSessions((current) =>
          sortSessions(
            current.map((session) =>
              session.session_id === sessionId ? updated : session,
            ),
          ),
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "无法更新置顶状态。");
      }
    },
    [browserId],
  );

  const removeSession = useCallback(
    async (sessionId: string) => {
      try {
        await deleteChatSession(browserId, sessionId);
        const remaining = sessions.filter((session) => session.session_id !== sessionId);
        if (remaining.length === 0) {
          const created = await createChatSession(browserId);
          setSessions([created]);
          await activateSession(created.session_id);
          return;
        }
        setSessions(remaining);
        if (activeSessionId === sessionId) {
          await activateSession(remaining[0].session_id);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "无法删除聊天。");
      }
    },
    [activateSession, activeSessionId, browserId, sessions],
  );

  const updateSessionSummary = useCallback((summary: ChatSessionSummary) => {
    setSessions((current) =>
      sortSessions(
        current.some((session) => session.session_id === summary.session_id)
          ? current.map((session) =>
              session.session_id === summary.session_id ? summary : session,
            )
          : [summary, ...current],
      ),
    );
  }, []);

  if (!activeSessionId || loading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background text-sm text-muted-foreground">
        {error ?? "正在加载聊天记录…"}
      </div>
    );
  }

  return (
    <div className="flex h-dvh bg-background">
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        mobileOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
        onNew={() => {
          setMobileSidebarOpen(false);
          void createNewSession();
        }}
        onSelect={(sessionId) => {
          setMobileSidebarOpen(false);
          void activateSession(sessionId);
        }}
        onRename={renameSession}
        onPin={pinSession}
        onDelete={removeSession}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex min-h-14 shrink-0 items-center gap-2 border-b px-3 sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="size-10 md:hidden"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="打开聊天列表"
          >
            <MenuIcon className="size-5" />
          </Button>
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight">DotaMind</div>
            <div className="text-xs text-muted-foreground">Dota 2 智能分析助手</div>
          </div>
          {error && <div className="ml-auto truncate text-xs text-destructive">{error}</div>}
        </header>
        <div className="min-h-0 flex-1">
          <ChatSessionRuntime
            key={activeSessionId}
            browserId={browserId}
            sessionId={activeSessionId}
            initialMessages={initialMessages}
            runtimeRuns={runtimeRuns}
            setRuntimeRuns={setRuntimeRuns}
            onSessionSummary={updateSessionSummary}
          />
        </div>
      </div>
    </div>
  );
};

type ChatSessionRuntimeProps = {
  browserId: string;
  sessionId: string;
  initialMessages: ThreadMessageLike[];
  runtimeRuns: RuntimeInfoMap;
  setRuntimeRuns: Dispatch<SetStateAction<RuntimeInfoMap>>;
  onSessionSummary: (summary: ChatSessionSummary) => void;
};

const ChatSessionRuntime = ({
  browserId,
  sessionId,
  initialMessages,
  runtimeRuns,
  setRuntimeRuns,
  onSessionSummary,
}: ChatSessionRuntimeProps) => {
  const updateRuntimeRun = useCallback(
    (messageId: string, updater: (run: RuntimeInfo) => RuntimeInfo) => {
      setRuntimeRuns((runs) => {
        const run = runs[messageId];
        return run ? { ...runs, [messageId]: updater(run) } : runs;
      });
    },
    [setRuntimeRuns],
  );

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_assistantMessageId }) {
        const query = latestUserText(messages);
        if (!query) throw new Error("请输入问题后再发送。");

        const messageId = unstable_assistantMessageId ?? crypto.randomUUID();
        setRuntimeRuns((runs) => ({
          ...runs,
          [messageId]: { messageId, phase: "planning", tools: [], status: "running" },
        }));
        let provisionalText = "";
        let receivedTerminalEvent = false;

        try {
          for await (const event of streamDotaMind(query, sessionId, browserId, abortSignal)) {
            switch (event.type) {
              case "phase":
                updateRuntimeRun(messageId, (run) => ({ ...run, phase: event.phase }));
                break;
              case "tool":
                updateRuntimeRun(messageId, (run) => ({
                  ...run,
                  tools: upsertTool(run.tools, event),
                }));
                break;
              case "answer_delta":
                provisionalText += event.delta;
                yield { content: [{ type: "text", text: provisionalText }] };
                break;
              case "result":
                receivedTerminalEvent = true;
                if (event.session) onSessionSummary(event.session);
                updateRuntimeRun(messageId, (run) => ({
                  ...run,
                  status: finalRunStatus(event.response.status),
                  durationMs: event.response.runtime?.duration_ms,
                }));
                yield { content: [{ type: "text", text: formatPlanResponse(event.response) }] };
                return;
              case "error":
                receivedTerminalEvent = true;
                updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
                yield {
                  content: [{ type: "text", text: formatStreamError(event.error_code, event.reason) }],
                };
                return;
            }
          }

          if (!receivedTerminalEvent) {
            updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
            yield { content: [{ type: "text", text: incompleteMessage }] };
          }
        } catch (cause) {
          if (cause instanceof Error && cause.name === "AbortError") {
            updateRuntimeRun(messageId, (run) => ({ ...run, status: "cancelled" }));
            yield { content: [{ type: "text", text: cancelledMessage }] };
            return;
          }
          updateRuntimeRun(messageId, (run) => ({ ...run, status: "failed" }));
          throw cause;
        }
      },
    }),
    [browserId, onSessionSummary, sessionId, setRuntimeRuns, updateRuntimeRun],
  );
  const runtime = useLocalRuntime(adapter, { initialMessages });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <RuntimeInfoProvider value={runtimeRuns}>
        <Thread />
      </RuntimeInfoProvider>
    </AssistantRuntimeProvider>
  );
};

const sortSessions = (sessions: ChatSessionSummary[]): ChatSessionSummary[] =>
  [...sessions].sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) return left.is_pinned ? -1 : 1;
    const updatedDifference = Date.parse(right.updated_at) - Date.parse(left.updated_at);
    return updatedDifference || right.session_id.localeCompare(left.session_id);
  });

const upsertTool = (tools: RuntimeTool[], incoming: RuntimeTool): RuntimeTool[] => {
  const index = tools.findIndex((tool) => tool.tool_call_id === incoming.tool_call_id);
  if (index === -1) return [...tools, incoming];
  return tools.map((tool, toolIndex) => (toolIndex === index ? incoming : tool));
};
