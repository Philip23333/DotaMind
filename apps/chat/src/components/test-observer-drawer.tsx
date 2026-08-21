"use client";

import { useAuiState } from "@assistant-ui/react";
import {
  CheckIcon,
  ChevronRightIcon,
  Code2Icon,
  CopyIcon,
  MessageSquareIcon,
  PanelRightIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import type {
  DotaMindObservation,
  DotaMindRuntimeInfo,
} from "@/lib/assistant-ui/run-event-converter";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import {
  groupToolObservations,
  serializeObservationPayload,
  type ToolObservationGroup,
} from "@/lib/assistant-ui/test-observer-model";
import { Button } from "@/components/ui/button";

type ObserverTab = "prompts" | "tools" | "outputs";

function useLatestRuntime(): { runId: string; runtime: DotaMindRuntimeInfo } | null {
  const custom = useAuiState((state) => {
    const message = state.thread.messages.findLast(
      (candidate) => candidate.role === "assistant",
    );
    return message?.metadata?.custom?.[DOTAMIND_ASSISTANT_METADATA_KEY];
  });
  if (!custom || typeof custom !== "object") return null;
  const metadata = custom as {
    runId?: string;
    runtime?: DotaMindRuntimeInfo;
  };
  if (!metadata.runId || !metadata.runtime) return null;
  return { runId: metadata.runId, runtime: metadata.runtime };
}

export function TestObserverDrawer() {
  const enabled = process.env.NEXT_PUBLIC_DOTAMIND_TEST_OBSERVER_ENABLED === "true";
  const latest = useLatestRuntime();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<ObserverTab>("prompts");

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const observations = latest?.runtime.observations ?? [];
  const prompts = observations.filter((item) => item.kind === "model_prompt");
  const outputs = observations.filter((item) => item.kind === "model_output");
  const tools = groupToolObservations(observations);

  if (!enabled) return null;

  return (
    <>
      {!open && (
        <Button
          variant="outline"
          size="icon"
          className="absolute right-3 top-3 z-30 size-10 bg-card/90 shadow-sm backdrop-blur"
          onClick={() => setOpen(true)}
          aria-label="打开测试观测器"
          title="测试观测器"
        >
          <PanelRightIcon className="size-4" />
        </Button>
      )}
      {open && (
        <div className="fixed inset-0 z-40" role="presentation">
          <button
            type="button"
            aria-label="关闭测试观测器"
            className="absolute inset-0 bg-black/10 backdrop-blur-[1px]"
            onClick={() => setOpen(false)}
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="测试观测器"
            className="absolute inset-y-0 right-0 flex w-full max-w-[620px] flex-col border-l bg-card shadow-2xl"
          >
            <header className="flex items-start gap-3 border-b px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 font-semibold">
                  <Code2Icon className="size-4" /> 测试观测器
                </div>
                <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                  {latest ? `Run ${latest.runId}` : "等待当前页面中的新 Run"}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={() => setOpen(false)}
                aria-label="关闭测试观测器"
              >
                <XIcon className="size-4" />
              </Button>
            </header>

            <nav className="grid grid-cols-3 gap-1 border-b p-2" aria-label="观测数据分类">
              <TabButton
                active={tab === "prompts"}
                onClick={() => setTab("prompts")}
                icon={<MessageSquareIcon className="size-3.5" />}
                label="模型 Prompt"
                count={prompts.length}
              />
              <TabButton
                active={tab === "tools"}
                onClick={() => setTab("tools")}
                icon={<WrenchIcon className="size-3.5" />}
                label="工具 I/O"
                count={tools.length}
              />
              <TabButton
                active={tab === "outputs"}
                onClick={() => setTab("outputs")}
                icon={<Code2Icon className="size-3.5" />}
                label="模型输出"
                count={outputs.length}
              />
            </nav>

            <div className="min-h-0 flex-1 overflow-y-auto bg-muted/20 p-3">
              {!latest ? (
                <EmptyState text="发送一条新消息后，这里会显示该 Run 的完整观测数据。" />
              ) : tab === "prompts" ? (
                <ObservationList observations={prompts} empty="尚未收到模型 Prompt。" />
              ) : tab === "outputs" ? (
                <ObservationList observations={outputs} empty="尚未收到模型输出。" />
              ) : tools.length ? (
                <div className="space-y-3">
                  {tools.map((tool, index) => (
                    <ToolObservationCard key={tool.key} tool={tool} defaultOpen={index === 0}>
                      <PayloadSection label="输入" value={tool.input?.payload ?? null} />
                      <PayloadSection label="输出" value={tool.output?.payload ?? null} />
                    </ToolObservationCard>
                  ))}
                </div>
              ) : (
                <EmptyState text="当前 Run 尚未执行工具。" />
              )}
            </div>

            <footer className="border-t px-4 py-2 text-[11px] text-muted-foreground">
              仅展示当前页面通过 Run 事件流收到的数据；后端还需启用
              <code className="mx-1">DOTAMIND_TEST_OBSERVER_ENABLED</code>
              ，且数据不会写入正式聊天记录。
            </footer>
          </aside>
        </div>
      )}
    </>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs transition-colors ${
        active ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
      }`}
    >
      {icon}
      <span>{label}</span>
      <span className="font-mono opacity-70">{count}</span>
    </button>
  );
}

function ObservationList({
  observations,
  empty,
}: {
  observations: DotaMindObservation[];
  empty: string;
}) {
  if (!observations.length) return <EmptyState text={empty} />;
  return (
    <div className="space-y-3">
      {observations.map((observation, index) => (
        <ObservationCard
          key={`${observation.attempt_index}:${observation.call_id}:${observation.kind}`}
          observation={observation}
          defaultOpen={index === 0}
        >
          <PayloadSection label="结构化数据" value={observation.payload} />
        </ObservationCard>
      ))}
    </div>
  );
}

function ObservationCard({
  observation,
  defaultOpen,
  children,
}: {
  observation: DotaMindObservation;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  return (
    <DisclosureCard
      title={observation.stage === "controller" ? "Controller" : "Answer"}
      detail={`Attempt ${observation.attempt_index + 1} · ${observation.call_id}`}
      defaultOpen={defaultOpen}
    >
      {children}
    </DisclosureCard>
  );
}

function ToolObservationCard({
  tool,
  defaultOpen,
  children,
}: {
  tool: ToolObservationGroup;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  return (
    <DisclosureCard
      title={tool.name}
      detail={`Attempt ${tool.attemptIndex + 1} · ${tool.callId}`}
      defaultOpen={defaultOpen}
    >
      {children}
    </DisclosureCard>
  );
}

function DisclosureCard({
  title,
  detail,
  defaultOpen,
  children,
}: {
  title: string;
  detail: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      className="group overflow-hidden rounded-lg border bg-card"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 select-none [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold">{title}</div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
            {detail}
          </div>
        </div>
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">
          JSON
        </span>
      </summary>
      <div className="border-t">{children}</div>
    </details>
  );
}

function PayloadSection({ label, value }: { label: string; value: unknown }) {
  const serialized = value == null ? null : serializeObservationPayload(value);
  return (
    <div className="border-b last:border-b-0">
      <div className="flex items-center justify-between gap-2 bg-muted/35 px-3 py-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {serialized && <CopyJsonButton value={serialized} label={label} />}
      </div>
      <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-[11px] leading-5 text-foreground">
        {serialized ?? "等待数据…"}
      </pre>
    </div>
  );
}

function CopyJsonButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
      aria-label={`复制${label} JSON`}
    >
      {copied ? <CheckIcon className="size-3" /> : <CopyIcon className="size-3" />}
      {copied ? "已复制" : "复制 JSON"}
    </button>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed bg-card/60 px-6 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}
