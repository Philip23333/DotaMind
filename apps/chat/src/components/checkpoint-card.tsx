"use client";

import { useAui } from "@assistant-ui/react";
import { useState, type FC } from "react";

import { Button } from "@/components/ui/button";
import { resumeChatRun } from "@/lib/chat-run-api";
import type {
  ChatRunCheckpoint,
} from "@/lib/dotamind-api";
import {
  streamDotaMindRun,
  type DotaMindRuntimeInfo,
} from "@/lib/assistant-ui/run-event-converter";

export const CheckpointCard: FC<{
  browserId?: string;
  checkpoint: ChatRunCheckpoint;
  runtime: DotaMindRuntimeInfo;
}> = ({ browserId, checkpoint, runtime }) => {
  const aui = useAui();
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectOption = async (optionId: string) => {
    if (
      !browserId ||
      !runtime.runId ||
      !runtime.sessionId ||
      !runtime.requestId ||
      runtime.lastSequence == null ||
      selectedOptionId
    ) {
      return;
    }

    setSelectedOptionId(optionId);
    setError(null);
    try {
      const assistantRuntime = aui.threads.__internal_getAssistantRuntime?.();
      if (!assistantRuntime) throw new Error("当前聊天运行时尚未准备好。");
      const source = assistantRuntime.thread.getMessageById(runtime.messageId).getState();

      await resumeChatRun(
        browserId,
        runtime.runId,
        checkpoint.checkpoint_type,
        optionId,
      );
      assistantRuntime.thread.resumeRun({
        parentId: source.parentId,
        sourceId: runtime.messageId,
        stream: (options) =>
          streamDotaMindRun({
            browserId,
            runId: runtime.runId,
            sessionId: runtime.sessionId,
            requestId: runtime.requestId,
            messageId: options.unstable_assistantMessageId ?? `${runtime.runId}:resume`,
            after: runtime.lastSequence,
            abortSignal: options.abortSignal,
          }),
      });
    } catch (cause) {
      setSelectedOptionId(null);
      setError(cause instanceof Error ? cause.message : "无法继续本次分析。");
    }
  };

  return (
    <section className="mb-4 rounded-xl border border-sky-200 bg-sky-50/70 p-3 text-sm dark:border-sky-900 dark:bg-sky-950/30">
      <p className="font-medium text-foreground">{checkpoint.question}</p>
      <div className="mt-3 grid gap-2">
        {checkpoint.options.map((option) => (
          <Button
            key={option.id}
            type="button"
            variant="outline"
            className="h-auto justify-start whitespace-normal bg-card px-3 py-2 text-left"
            disabled={selectedOptionId !== null || !browserId}
            onClick={() => void selectOption(option.id)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      {selectedOptionId && !error && (
        <p className="mt-2 text-xs text-muted-foreground">已提交选择，正在继续分析…</p>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </section>
  );
};
