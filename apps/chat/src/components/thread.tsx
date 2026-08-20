"use client";

import { MarkdownText } from "@/components/markdown-text";
import { RuntimeInfoCard, useRuntimeInfo } from "@/components/runtime-info";
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
import { cancelChatRun } from "@/lib/chat-run-api";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import { useRef, useState, type FC } from "react";

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
          <AuiIf condition={(state) => state.thread.messages.length === 0}>
            <Welcome />
          </AuiIf>

          <div className="flex flex-col gap-10 pb-16 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage />}
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
  <div className="flex flex-1 flex-col items-center justify-center pb-24 text-center">
    <div className="mb-6 flex size-[150px] items-center justify-center rounded-[2rem] bg-[#b92d1e] text-[#fff4e1] shadow-[0_16px_36px_rgb(115_31_24_/_24%)]">
      <svg className="size-24" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d={siDota2.path} />
      </svg>
    </div>
    <h1 className="text-2xl font-semibold tracking-tight">今天想分析什么？</h1>
    <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
      可以询问英雄克制、阵容配合、对线表现或版本数据。
    </p>
  </div>
);

const ThreadMessage: FC = () => {
  const role = useAuiState((state) => state.message.role);
  return role === "user" ? <UserMessage /> : <AssistantMessage />;
};

const UserMessage: FC = () => (
    <MessagePrimitive.Root className="flex min-w-0 justify-end">
    <div className="max-w-[90%] min-w-0 rounded-2xl bg-muted px-3 py-2.5 leading-relaxed wrap-break-word sm:max-w-[85%]">
      <MessagePrimitive.Parts />
    </div>
  </MessagePrimitive.Root>
);

const AssistantMessage: FC = () => {
  const messageId = useAuiState((state) => state.message.id);
  const runtimeInfo = useRuntimeInfo(messageId);

  return (
    <MessagePrimitive.Root className="group relative min-w-0 pr-2 sm:pr-8">
      <div className="min-w-0 leading-relaxed wrap-break-word">
        {runtimeInfo && <RuntimeInfoCard run={runtimeInfo} />}
        {runtimeInfo?.status === "running" && runtimeInfo.phase === "answering" && (
          <p className="mb-2 text-xs text-muted-foreground">生成中 · 待核验</p>
        )}
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
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
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

const Composer: FC<{ browserId?: string }> = ({ browserId }) => {
  const aui = useAui();
  const [isFocused, setIsFocused] = useState(false);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const isNewThread = useAuiState((state) => state.thread.messages.length === 0);

  const sendTiUpdatePrompt = () => {
    if (isRunning) return;
    aui.composer.setText("本届TI最新战况");
    aui.composer.send();
  };

  return (
    <div className="relative">
      {isNewThread && isFocused && !isRunning && (
        <div className="absolute bottom-full left-0 mb-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="rounded-full bg-card shadow-sm"
            onMouseDown={(event) => event.preventDefault()}
            onClick={sendTiUpdatePrompt}
          >
            <SparklesIcon className="size-3.5" />
            本届TI最新战况
          </Button>
        </div>
      )}
      <ComposerPrimitive.Root className="rounded-3xl border bg-popover p-1.5 shadow-sm focus-within:ring-2 focus-within:ring-ring/30 sm:p-2">
        <ComposerPrimitive.Input
          placeholder="询问英雄、阵容、对线或版本数据…"
          className="max-h-40 min-h-12 w-full min-w-0 resize-none bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted-foreground"
          rows={1}
          autoFocus
          enterKeyHint="send"
          aria-label="消息输入框"
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
        />
        <div className="flex justify-end px-1 pb-1">
          <AuiIf condition={(state) => !state.thread.isRunning}>
            <ComposerPrimitive.Send
              render={
                <Button size="icon" className="size-8 rounded-full" aria-label="发送消息" />
              }
            >
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          </AuiIf>
          <AuiIf condition={(state) => state.thread.isRunning}>
            <DotaMindStopButton browserId={browserId} />
          </AuiIf>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
};

const DotaMindStopButton: FC<{ browserId?: string }> = ({ browserId }) => {
  const message = useAuiState((state) =>
    state.thread.messages.findLast(
      (candidate) => candidate.role === "assistant" && candidate.status?.type === "running",
    ),
  );
  const [stopping, setStopping] = useState(false);
  const requestedRunRef = useRef<string | null>(null);
  const custom = message?.metadata?.custom?.[DOTAMIND_ASSISTANT_METADATA_KEY];
  const runId =
    custom && typeof custom === "object" && "runId" in custom && typeof custom.runId === "string"
      ? custom.runId
      : null;

  const stop = async () => {
    if (!browserId || !runId || stopping || requestedRunRef.current === runId) return;
    requestedRunRef.current = runId;
    setStopping(true);
    try {
      await cancelChatRun(browserId, runId);
    } catch {
      requestedRunRef.current = null;
      setStopping(false);
    }
  };

  return (
    <Button
      size="icon"
      className="size-8 rounded-full"
      aria-label="停止生成"
      disabled={!runId || stopping}
      onClick={() => void stop()}
    >
      <SquareIcon className="size-3 fill-current" />
    </Button>
  );
};
