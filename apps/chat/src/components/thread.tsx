"use client";

import { MarkdownText } from "@/components/markdown-text";
import { CheckpointCard } from "@/components/checkpoint-card";
import { RuntimeInfoCard, useRuntimeInfo } from "@/components/runtime-info";
import { SessionTracePanel } from "@/components/session-trace-panel";
import { TraceDownloadAction } from "@/components/trace-download-action";
import { Button } from "@/components/ui/button";
import {
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CopyIcon,
  SquareIcon,
  SparklesIcon,
} from "lucide-react";
import { siDota2 } from "simple-icons";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import { useEffect, useMemo, useRef, type FC } from "react";
import { createUuidV4 } from "@/lib/uuid";
import { getChatSession, transcriptToInitialMessages } from "@/lib/dotamind-api";
import { useDotaMindThreadState } from "@/lib/assistant-ui/dotamind-transport-runtime";
import type { DotamindMessageMetadata } from "@/lib/assistant-ui/dotamind-run-state";

export const Thread: FC<{ browserId?: string }> = ({ browserId }) => {
  return (
    <ThreadPrimitive.Root className="chat-main-surface relative flex h-full min-w-0 flex-col overflow-hidden bg-card">
      <div className="chat-main-surface__mark" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d={siDota2.path} />
        </svg>
      </div>
      <ThreadPrimitive.Viewport className="relative z-10 flex min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto scroll-smooth">
        <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-1 flex-col px-3 pt-4 sm:px-6 sm:pt-6">
          <SessionTracePanel browserId={browserId} />
          <AuiIf condition={(state) => state.thread.messages.length === 0}>
            <Welcome />
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
            <Composer browserId={browserId} />
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

const Welcome: FC = () => (
  <div className="welcome-intro flex flex-1 flex-col items-center justify-center pb-24 text-center">
    <div className="mb-6 flex size-[150px] items-center justify-center rounded-[2rem] bg-[#b92d1e] text-[#fff4e1] shadow-[0_16px_36px_rgb(115_31_24_/_24%)]">
      <svg className="size-24" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d={siDota2.path} />
      </svg>
    </div>
    <h1 className="text-2xl font-semibold tracking-tight">🔥TI正在火热进行中！</h1>
    <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
      快捷查询赛程、比赛详情与选手数据等
    </p>
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
  const messageId = useAuiState((state) => state.message.id);
  const metadata = useAuiState((state) => state.message.metadata?.custom);
  const trace = useMemo(() => traceFromMetadata(metadata), [metadata]);
  const transport = useMemo(() => transportMetadataFromCustom(metadata), [metadata]);
  const runtimeInfo = useRuntimeInfo(messageId);

  return (
    <MessagePrimitive.Root className="group relative min-w-0 pr-2 sm:pr-8">
      <div className="min-w-0 leading-relaxed wrap-break-word">
        {runtimeInfo && <RuntimeInfoCard run={runtimeInfo} />}
        {runtimeInfo?.status === "waiting_input" && runtimeInfo.checkpoint && (
          <CheckpointCard
            browserId={browserId}
            checkpoint={runtimeInfo.checkpoint}
            runtime={runtimeInfo}
          />
        )}
        {runtimeInfo?.status === "running" && runtimeInfo.phase === "answering" && (
          <p className="mb-2 text-xs text-muted-foreground">生成中 · 待核验</p>
        )}
        {transport?.source === "pending" && transport.connection_status === "sending" && (
          <p className="mb-2 text-xs text-muted-foreground">正在连接…</p>
        )}
        {transport?.run?.status === "running" && transport.run.answer.status === "pending" && (
          <p className="mb-2 text-xs text-muted-foreground">正在分析…</p>
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

const Composer: FC<{ browserId?: string }> = ({ browserId }) => {
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const isNewThread = useAuiState((state) => state.thread.messages.length === 0);
  const { entry, snapshot } = useDotaMindThreadState();
  const remoteSessionId = useAuiState((state) => state.threadListItem.remoteId);
  const threadStatus = useAuiState((state) => state.threadListItem.status);
  const composerText = useAuiState((state) => state.composer.text);
  const submitLock = useRef(false);
  const isBusy = isRunning || snapshot.is_submitting || snapshot.connection?.status === "sending";

  useEffect(() => {
    if (isRunning || (snapshot.connection && snapshot.connection.status !== "sending")) {
      submitLock.current = false;
    }
  }, [isRunning, snapshot.connection]);

  const sendMessage = async () => {
    if (submitLock.current || isBusy || !aui.composer.getState().text.trim()) return;
    if (!entry.beginSubmission()) return;
    submitLock.current = true;
    let accepted = false;
    let failureScope: "initialization" | "history" = "initialization";
    try {
      let sessionId = aui.threadListItem.getState().remoteId;
      if (!sessionId) {
        if (threadStatus !== "new") throw new Error("session initialization failed");
        const initialized = await aui.threadListItem.initialize();
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
        if (entry.getSnapshot().history_status !== "ready") throw new Error("history unavailable");
        await entry.waitForSessionRenderCommit(sessionId);
      }

      entry.captureVisibleMessages(aui.thread.getState().messages);
      entry.acceptRequest({
        session_id: sessionId,
        request_id: createUuidV4(),
        created_at: new Date().toISOString(),
        command: null,
      });
      accepted = true;
      aui.composer.send();
    } catch {
      if (accepted) {
        const request = entry.getSnapshot().accepted_request;
        if (request) entry.setConnection(request.request_id, "error");
      } else {
        entry.finishSubmissionWithError(failureScope);
        submitLock.current = false;
      }
    }
  };

  const sendTiUpdatePrompt = () => {
    if (isBusy) return;
    aui.composer.setText("本届TI最新战况");
    void sendMessage();
  };

  return (
    <div className="relative">
      {isNewThread && !isRunning && (
        <div className="absolute inset-x-0 bottom-full mb-[5px]">
          <Button
            type="button"
            variant="ghost"
            size="lg"
            className="h-11 w-full justify-start rounded-lg bg-transparent px-4 text-base text-foreground/55 shadow-none hover:bg-popover hover:text-foreground hover:shadow-[0_-5px_14px_rgb(0_0_0_/_8%)] focus-visible:bg-popover focus-visible:text-foreground focus-visible:shadow-[0_-5px_14px_rgb(0_0_0_/_8%)]"
            onMouseDown={(event) => event.preventDefault()}
            onClick={sendTiUpdatePrompt}
          >
            <SparklesIcon className="size-4" />
            本届TI最新战况
          </Button>
        </div>
      )}
      <ComposerPrimitive.Root
        onSubmit={(event) => {
          event.preventDefault();
          void sendMessage();
        }}
        className="rounded-3xl border bg-popover p-1.5 shadow-sm focus-within:ring-2 focus-within:ring-ring/30 sm:p-2"
      >
        <ComposerPrimitive.Input
          placeholder="询问英雄、阵容、对线或版本数据…"
          className="max-h-40 min-h-12 w-full min-w-0 resize-none bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted-foreground"
          rows={1}
          autoFocus
          enterKeyHint="send"
          aria-label="消息输入框"
        />
        <div className="flex justify-end px-1 pb-1">
          {!isBusy && (
            <Button
              type="button"
              size="icon"
              className="size-8 rounded-full"
              aria-label="发送消息"
              disabled={
                !composerText.trim() ||
                snapshot.history_status !== "ready" ||
                snapshot.is_submitting
              }
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => void sendMessage()}
            >
              <ArrowUpIcon className="size-4" />
            </Button>
          )}
          {isBusy && (
            <DotaMindStopButton />
          )}
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
    </div>
  );
};

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
