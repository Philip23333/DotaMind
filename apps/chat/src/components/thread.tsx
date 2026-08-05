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
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CopyIcon,
  SquareIcon,
} from "lucide-react";
import { cancelChatRun } from "@/lib/chat-run-api";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import { useRef, useState, type FC } from "react";

export const Thread: FC<{ browserId?: string }> = ({ browserId }) => {
  return (
    <ThreadPrimitive.Root className="flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <ThreadPrimitive.Viewport className="relative flex min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto scroll-smooth">
        <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-1 flex-col px-3 pt-4 sm:px-6 sm:pt-6">
          <AuiIf condition={(state) => state.thread.messages.length === 0}>
            <Welcome />
          </AuiIf>

          <div className="flex flex-col gap-7 pb-8 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mt-auto bg-background/95 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur sm:pb-6">
            <ThreadPrimitive.ScrollToBottom
              render={
                <Button
                  variant="outline"
                  size="icon"
                  className="absolute -top-11 left-1/2 size-8 -translate-x-1/2 rounded-full bg-background disabled:invisible"
                  aria-label="滚动到底部"
                />
              }
            >
              <ArrowDownIcon className="size-4" />
            </ThreadPrimitive.ScrollToBottom>
            <Composer browserId={browserId} />
            <p className="mt-2 text-center text-xs text-muted-foreground">
              DotaMind 可能会出错，请结合证据判断。
            </p>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const Welcome: FC = () => (
  <div className="flex flex-1 flex-col items-center justify-center pb-24 text-center">
    <div className="mb-4 flex size-11 items-center justify-center rounded-2xl bg-primary text-sm font-bold text-primary-foreground">
      DM
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
        autohide="not-last"
        className="mt-2 flex items-center gap-1 text-muted-foreground"
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

const Composer: FC<{ browserId?: string }> = ({ browserId }) => (
  <ComposerPrimitive.Root className="rounded-3xl border bg-background p-1.5 shadow-sm focus-within:ring-2 focus-within:ring-ring/30 sm:p-2">
    <ComposerPrimitive.Input
      placeholder="询问英雄、阵容、对线或版本数据…"
      className="max-h-40 min-h-12 w-full min-w-0 resize-none bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted-foreground"
      rows={1}
      autoFocus
      enterKeyHint="send"
      aria-label="消息输入框"
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
);

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
