"use client";

import { MarkdownText } from "@/components/markdown-text";
import { TraceDownloadAction } from "@/components/trace-download-action";
import { Button } from "@/components/ui/button";
import { RunProcessPanel } from "@/components/run-process-panel";
import {
  ComposerModeSwitch,
  composerModeLabel,
  composeModeMessage,
  composerModePlaceholder,
  type ComposerMode,
} from "@/components/composer-mode-switch";
import {
  RecentSeriesContent,
  useRecentSeries,
  type RecentSeriesState,
} from "@/components/recent-series";
import {
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  unstable_useComposerInput,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CopyIcon,
  RefreshCwIcon,
  SquareIcon,
} from "lucide-react";
import { siDota2 } from "simple-icons";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import { useEffect, useMemo, useRef, useState, type FC } from "react";
import { createUuidV4 } from "@/lib/uuid";
import { getChatSession, transcriptToInitialMessages } from "@/lib/dotamind-api";
import { useDotaMindThreadState } from "@/lib/assistant-ui/dotamind-transport-runtime";
import type { DotamindMessageMetadata } from "@/lib/assistant-ui/dotamind-run-state";
import { recentSeriesDisplayName, type RecentSeriesCandidate } from "@/lib/home-api";

export const Thread: FC<{ browserId?: string }> = ({ browserId }) => {
  const aui = useAui();
  const recentSeries = useRecentSeries();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const threadStatus = useAuiState((state) => state.threadListItem.status);
  const { entry, snapshot } = useDotaMindThreadState();
  const submitLock = useRef(false);
  const isBusy = isRunning || snapshot.is_submitting || snapshot.connection?.status === "sending";

  useEffect(() => {
    if (isRunning || (snapshot.connection && snapshot.connection.status !== "sending")) {
      submitLock.current = false;
    }
  }, [isRunning, snapshot.connection]);

  const sendMessage = async (message: string): Promise<boolean> => {
    const currentSnapshot = entry.getSnapshot();
    const busyNow = aui.thread.getState().isRunning || currentSnapshot.is_submitting ||
      currentSnapshot.connection?.status === "sending";
    if (submitLock.current || busyNow || !message.trim()) return false;
    if (!entry.beginSubmission()) return false;
    submitLock.current = true;
    let accepted = false;
    let failureScope: "initialization" | "history" = "initialization";
    const targetThreadId = aui.threadListItem.getState().id;
    const ensureTargetThreadIsActive = () => {
      if (aui.threadListItem.getState().id !== targetThreadId) {
        throw new Error("active thread changed during submission preparation");
      }
    };
    try {
      let sessionId = aui.threadListItem.getState().remoteId;
      if (!sessionId) {
        if (threadStatus !== "new") throw new Error("session initialization failed");
        const initialized = await aui.threadListItem.initialize();
        ensureTargetThreadIsActive();
        sessionId = initialized.remoteId;
        entry.markNewSession(sessionId);
        await entry.waitForSessionRenderCommit(sessionId);
      } else {
        failureScope = "history";
        await entry.loadHistory(sessionId, async (signal) => {
          if (!browserId) throw new Error("browser identity is unavailable");
          const response = await getChatSession(browserId, sessionId!, signal);
          return transcriptToInitialMessages(response);
        });
        ensureTargetThreadIsActive();
        if (entry.getSnapshot().history_status !== "ready") throw new Error("history unavailable");
        await entry.waitForSessionRenderCommit(sessionId);
      }

      ensureTargetThreadIsActive();
      entry.captureVisibleMessages(aui.thread.getState().messages);
      entry.acceptRequest({
        session_id: sessionId,
        request_id: createUuidV4(),
        created_at: new Date().toISOString(),
        command: null,
      });
      accepted = true;
      aui.thread.append({
        role: "user",
        content: [{ type: "text", text: message }],
      });
      return true;
    } catch {
      if (accepted) {
        const request = entry.getSnapshot().accepted_request;
        if (request) entry.setConnection(request.request_id, "error");
      } else {
        entry.finishSubmissionWithError(failureScope);
        submitLock.current = false;
      }
      return false;
    }
  };

  return (
    <ThreadPrimitive.Root className="chat-main-surface relative flex h-full min-w-0 flex-col overflow-hidden bg-card">
      <div className="chat-main-surface__mark" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d={siDota2.path} />
        </svg>
      </div>
      <ThreadPrimitive.Viewport className="relative z-10 flex min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto scroll-smooth">
        <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-1 flex-col px-3 pt-16 sm:px-6 sm:pt-16">
          <AuiIf condition={(state) => state.thread.messages.length === 0}>
            <Welcome
              recentSeries={recentSeries}
              isBusy={isBusy}
              onRefresh={recentSeries.retry}
              onSelect={(series) => { void sendMessage(seriesQueryText(series)); }}
            />
          </AuiIf>

          <div className="flex flex-col gap-10 pb-16 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage browserId={browserId} />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mt-auto bg-card/95 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur sm:pb-6">
            <ThreadPrimitive.ScrollToBottom
              render={
                <Button
                  variant="outline"
                  size="icon"
                  className="absolute -top-11 left-1/2 size-8 -translate-x-1/2 rounded-full bg-card disabled:invisible"
                  aria-label="滚动到底部"
                />
              }
            >
              <ArrowDownIcon className="size-4" />
            </ThreadPrimitive.ScrollToBottom>
            <Composer
              browserId={browserId}
              isBusy={isBusy}
              onSendMessage={sendMessage}
            />
            <a
              href="https://beian.miit.gov.cn/"
              target="_blank"
              rel="noreferrer"
              className="mt-2 block text-center text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            >
              鄂ICP备2026044062号-1
            </a>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const Welcome: FC<{
  recentSeries: RecentSeriesState;
  isBusy: boolean;
  onRefresh: () => void;
  onSelect: (series: RecentSeriesCandidate) => void;
}> = ({ recentSeries, isBusy, onRefresh, onSelect }) => (
  <div className="welcome-intro flex flex-1 flex-col items-center justify-center gap-5 pb-12 text-center sm:pb-20">
    <div className="flex items-center gap-3">
      <div className="flex size-[67px] items-center justify-center rounded-2xl bg-[#b92d1e] text-[#fff4e1] shadow-[0_8px_20px_rgb(115_31_24_/_20%)]">
        <svg className="size-[43px]" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="currentColor" d={siDota2.path} />
        </svg>
      </div>
      <h1 className="text-[1.8rem] font-semibold tracking-tight">DotaMind</h1>
    </div>
    <section className="w-full max-w-2xl text-left" aria-label="🔥最近赛事">
      <div className="mb-1 flex items-center justify-between px-3">
        <h2 className="text-sm font-semibold">🔥最近赛事</h2>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="刷新近期赛事"
          title="刷新近期赛事"
          disabled={recentSeries.loading}
          onClick={onRefresh}
        >
          <RefreshCwIcon className={`size-3.5 ${recentSeries.loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>
      <RecentSeriesContent
        state={recentSeries}
        count={5}
        disabled={isBusy}
        onSelect={onSelect}
        onRetry={recentSeries.retry}
      />
    </section>
  </div>
);

const ThreadMessage: FC<{ browserId?: string }> = ({ browserId }) => {
  const messageId = useAuiState((state) => state.message.id);
  const role = useAuiState((state) => state.message.role);
  return role === "user"
    ? <UserMessage key={messageId} />
    : <AssistantMessage key={messageId} browserId={browserId} />;
};

const UserMessage: FC = () => (
    <MessagePrimitive.Root className="flex min-w-0 justify-end">
    <div className="max-w-[90%] min-w-0 rounded-2xl bg-muted px-3 py-2.5 leading-relaxed wrap-break-word sm:max-w-[85%]">
      <MessagePrimitive.Parts />
    </div>
  </MessagePrimitive.Root>
);

const AssistantMessage: FC<{ browserId?: string }> = ({ browserId }) => {
  const metadata = useAuiState((state) => state.message.metadata?.custom);
  const trace = useMemo(() => traceFromMetadata(metadata), [metadata]);
  const transport = useMemo(() => transportMetadataFromCustom(metadata), [metadata]);

  return (
    <MessagePrimitive.Root className="group relative min-w-0 pr-2 sm:pr-8">
      <div className="min-w-0 leading-relaxed wrap-break-word">
        {transport?.source === "pending" && transport.connection_status === "sending" && (
          <p className="mb-2 text-xs text-muted-foreground">正在连接…</p>
        )}
        <RunProcessPanel
          key={transport?.request_id}
          run={transport?.run}
          connectionStatus={transport?.connection_status}
        />
        {(transport?.run?.status === "cancelled" || transport?.connection_status === "cancelled") && (
          <p role="status" className="mt-2 text-xs text-muted-foreground">已停止</p>
        )}
        {transport?.run?.status === "failed" && transport.run.error?.scope === "execution" && (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {transport.run.error.message}
          </p>
        )}
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
        {transport?.persistence === "failed" && (
          <p role="status" className="mt-2 text-xs text-destructive">
            回答已生成，但未能确认保存结果，请重试保存。
          </p>
        )}
        {transport?.connection_status === "error" && (
          <p role="status" className="mt-2 text-xs text-destructive">
            连接中断，已保留当前可见内容。
          </p>
        )}
        {transport?.connection_status === "ended" && transport.run?.status === "running" && (
          <p role="status" className="mt-2 text-xs text-destructive">
            连接已结束，最终结果未确认。
          </p>
        )}
        <MessagePrimitive.Error>
          <ErrorPrimitive.Root className="mt-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            <ErrorPrimitive.Message />
          </ErrorPrimitive.Root>
        </MessagePrimitive.Error>
      </div>
      <ActionBarPrimitive.Root
        hideWhenRunning
        className="absolute left-0 top-full mt-2 flex items-center gap-1 text-muted-foreground"
      >
        <AuiIf condition={(state) => state.message.status?.type === "complete"}>
          <ActionBarPrimitive.Copy
            render={
              <Button variant="ghost" size="icon" className="size-8" aria-label="复制回答" />
            }
          >
            <AuiIf condition={(state) => state.message.isCopied}>
              <CheckIcon className="size-4" />
            </AuiIf>
            <AuiIf condition={(state) => !state.message.isCopied}>
              <CopyIcon className="size-4" />
            </AuiIf>
          </ActionBarPrimitive.Copy>
        </AuiIf>
        {browserId && trace && (
          <TraceDownloadAction browserId={browserId} traceId={trace.trace_id} />
        )}
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

function traceFromMetadata(custom: unknown): { trace_id: string; expires_at: string } | null {
  if (!custom || typeof custom !== "object") return null;
  const dotamind = (custom as Record<string, unknown>)[DOTAMIND_ASSISTANT_METADATA_KEY];
  if (!dotamind || typeof dotamind !== "object") return null;
  const trace = (dotamind as Record<string, unknown>).trace;
  if (!trace || typeof trace !== "object") return null;
  const value = trace as Record<string, unknown>;
  return typeof value.trace_id === "string" && typeof value.expires_at === "string"
    ? { trace_id: value.trace_id, expires_at: value.expires_at }
    : null;
}

const Composer: FC<{
  browserId?: string;
  isBusy: boolean;
  onSendMessage: (message: string) => Promise<boolean>;
}> = ({ browserId, isBusy, onSendMessage }) => {
  const aui = useAui();
  const composerInput = unstable_useComposerInput();
  const { entry, snapshot } = useDotaMindThreadState();
  const remoteSessionId = useAuiState((state) => state.threadListItem.remoteId);
  const threadItemId = useAuiState((state) => state.threadListItem.id);
  const composerText = useAuiState((state) => state.composer.text);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const previousThreadIdRef = useRef(threadItemId);
  const draftRevisionRef = useRef(0);
  const modeRevisionRef = useRef(0);
  const [mode, setMode] = useState<ComposerMode>(null);

  useEffect(() => {
    if (previousThreadIdRef.current === threadItemId) return;
    previousThreadIdRef.current = threadItemId;
    modeRevisionRef.current += 1;
    setMode(null);
  }, [threadItemId]);

  const changeMode = (nextMode: ComposerMode) => {
    modeRevisionRef.current += 1;
    setMode(nextMode);
    requestAnimationFrame(() => {
      composerInputRef.current?.focus();
    });
  };

  const submitComposerMessage = async () => {
    const rawText = aui.composer.getState().text;
    if (!rawText.trim()) return;

    const capturedMode = mode;
    const capturedDraftRevision = draftRevisionRef.current;
    const capturedModeRevision = modeRevisionRef.current;
    const capturedThreadItemId = aui.threadListItem.getState().id;
    const accepted = await onSendMessage(composeModeMessage(capturedMode, rawText));
    if (!accepted || aui.threadListItem.getState().id !== capturedThreadItemId) return;

    if (draftRevisionRef.current === capturedDraftRevision) {
      composerInput.setText("");
      draftRevisionRef.current += 1;
      if (modeRevisionRef.current === capturedModeRevision) {
        modeRevisionRef.current += 1;
        setMode(null);
      }
    }
  };

  return (
    <ComposerPrimitive.Root
      onSubmit={(event) => {
        event.preventDefault();
        void submitComposerMessage();
      }}
      className="rounded-3xl border bg-popover p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/30 sm:p-2.5"
    >
      <div className="relative">
        {mode !== null && (
          <span
            data-testid="composer-mode-indicator"
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-2 z-10 select-none text-base font-semibold leading-6 text-foreground"
          >
            {composerModeLabel(mode)}：
          </span>
        )}
        <ComposerPrimitive.Input
          placeholder={composerModePlaceholder(mode)}
          className="max-h-40 min-h-[5.5rem] w-full min-w-0 resize-none overflow-y-auto bg-transparent px-3 py-2 text-base leading-6 outline-none placeholder:text-muted-foreground"
          style={mode !== null ? { textIndent: "5.5em" } : undefined}
          rows={1}
          ref={composerInputRef}
          autoFocus
          enterKeyHint="send"
          aria-label="消息输入框"
          onChange={() => {
            draftRevisionRef.current += 1;
          }}
        />
      </div>
      <div className="flex min-w-0 items-end justify-between gap-2 px-1 pb-1 pt-1">
        <ComposerModeSwitch mode={mode} onChange={changeMode} />
        <div className="flex shrink-0 items-center justify-end">
          {!isBusy && (
            <Button
              type="button"
              size="icon"
              className="size-10 rounded-full"
              aria-label="发送消息"
              disabled={
                !composerText.trim() ||
                snapshot.history_status !== "ready" ||
                snapshot.is_submitting
              }
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => void submitComposerMessage()}
            >
              <ArrowUpIcon className="size-4" />
            </Button>
          )}
          {isBusy && (
            <DotaMindStopButton />
          )}
        </div>
      </div>
      {snapshot.is_submitting && (
        <p role="status" className="px-3 pb-2 text-xs text-muted-foreground">正在准备会话…</p>
      )}
      {snapshot.notice === "initialization" && (
        <p role="alert" className="px-3 pb-2 text-xs text-destructive">无法建立聊天，请重试。</p>
      )}
      {snapshot.notice === "history" && (
        <div className="flex items-center gap-2 px-3 pb-2 text-xs text-destructive">
          <span role="alert">聊天记录未能加载。</span>
          {remoteSessionId && browserId && (
            <button
              type="button"
              className="underline underline-offset-2"
              onClick={() => void entry.loadHistory(remoteSessionId, async (signal) => {
                const response = await getChatSession(browserId, remoteSessionId, signal);
                return transcriptToInitialMessages(response);
              })}
            >
              重试
            </button>
          )}
        </div>
      )}
    </ComposerPrimitive.Root>
  );
};

function seriesQueryText(series: RecentSeriesCandidate): string {
  const name = recentSeriesDisplayName(series);
  return `查询赛事「${name}」的最新战况和赛程（赛事届次 Series ID：${series.series_id}）。`;
}

function transportMetadataFromCustom(custom: unknown): DotamindMessageMetadata | null {
  if (!custom || typeof custom !== "object") return null;
  const value = (custom as Record<string, unknown>)[DOTAMIND_ASSISTANT_METADATA_KEY];
  if (!value || typeof value !== "object") return null;
  const metadata = value as DotamindMessageMetadata;
  return typeof metadata.request_id === "string" ? metadata : null;
}

const DotaMindStopButton: FC = () => {
  const aui = useAui();

  return (
    <Button
      size="icon"
      className="size-8 rounded-full"
      aria-label="停止生成"
      onClick={() => aui.thread.cancelRun()}
    >
      <SquareIcon className="size-3 fill-current" />
    </Button>
  );
};
