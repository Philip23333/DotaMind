"use client";

import type { PlanStreamEvent } from "@/lib/dotamind-api";
import type { DotaMindRuntimeInfo } from "@/lib/assistant-ui/run-event-converter";
import { DOTAMIND_ASSISTANT_METADATA_KEY } from "@/lib/assistant-ui/migration-contract";
import { formatToolFailure } from "@/lib/runtime-failure";
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleAlertIcon,
  LoaderCircleIcon,
  WrenchIcon,
} from "lucide-react";
import { useAuiState } from "@assistant-ui/react";
import { useState, type FC } from "react";

type RunStatus = "running" | "waiting_input" | "completed" | "failed" | "cancelled";

export type RuntimeTool = Extract<PlanStreamEvent, { type: "tool" }>;

export type RuntimeInfo = DotaMindRuntimeInfo;

export const useRuntimeInfo = (messageId: string) => {
  const custom = useAuiState((state) => state.message.metadata?.custom?.[DOTAMIND_ASSISTANT_METADATA_KEY]);
  if (!messageId) return null;
  if (!custom || typeof custom !== "object") return null;
  const runtime = (custom as { runtime?: RuntimeInfo }).runtime;
  return runtime ?? null;
};

const phaseLabels: Record<RuntimeInfo["phase"], string> = {
  planning: "分析问题",
  tool_execution: "使用工具",
  answering: "整理回答",
  reviewing: "核验依据",
};

const toolLabels: Record<string, string> = {
  "artifact.grep": "检索存档内容",
  "artifact.read": "读取存档内容",
};

const statusLabel: Record<RunStatus, string> = {
  running: "进行中",
  waiting_input: "等待选择",
  completed: "已完成",
  failed: "未完成",
  cancelled: "已取消",
};

export const RuntimeInfoCard: FC<{ run: RuntimeInfo }> = ({ run }) => {
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const isOpen = manualOpen ?? run.status !== "completed";
  const completedToolCount = run.tools.filter((tool) => tool.status === "ok").length;
  const isRunning = run.status === "running";

  return (
    <details
      className="mb-4 rounded-xl border bg-muted/35 text-sm"
      open={isOpen}
      onToggle={(event) => setManualOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        {isRunning ? (
          <LoaderCircleIcon className="size-4 animate-spin" />
        ) : run.status === "waiting_input" ? (
          <CircleAlertIcon className="size-4 text-sky-600" />
        ) : run.status === "completed" ? (
          <CheckCircle2Icon className="size-4 text-emerald-600" />
        ) : (
          <CircleAlertIcon className="size-4 text-amber-600" />
        )}
        <span className="font-medium text-foreground">
          {statusLabel[run.status]}
          {run.status === "completed" && ` · 使用 ${completedToolCount} 个工具`}
          {run.durationMs != null && ` · ${(run.durationMs / 1000).toFixed(1)} 秒`}
        </span>
        <ChevronDownIcon className="ml-auto size-4 transition-transform [[open]_&]:rotate-180" />
      </summary>
      <div className="border-t px-3 py-2.5">
        <ol className="space-y-2 text-muted-foreground">
          {Object.entries(phaseLabels).map(([phase, label]) => {
            const reached = Object.keys(phaseLabels).indexOf(phase) <= Object.keys(phaseLabels).indexOf(run.phase);
            return (
              <li key={phase} className={reached ? "text-foreground" : undefined}>
                {reached ? "●" : "○"} {label}
                {phase === run.phase && isRunning ? "…" : ""}
              </li>
            );
          })}
        </ol>
        {run.tools.length > 0 && (
          <div className="mt-3 border-t pt-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-foreground">
              <WrenchIcon className="size-3.5" /> 工具调用
            </div>
            <ul className="space-y-1 text-muted-foreground">
              {run.tools.map((tool) => (
                <li key={tool.tool_call_id} title={tool.tool}>
                  {tool.status === "running" ? "●" : tool.status === "ok" ? "✓" : "!"}{" "}
                  {toolLabels[tool.tool] ?? tool.tool}
                  {tool.status === "running" ? "…" : ""}
                  {tool.status === "error" && tool.handler_entered === false
                    ? " · 未执行"
                    : tool.latency_ms != null
                      ? ` · ${tool.latency_ms}ms`
                      : ""}
                  {tool.status === "error" && tool.failure_code && (
                    <span className="block pl-4 text-xs">{formatToolFailure(tool.failure_code)}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
};
