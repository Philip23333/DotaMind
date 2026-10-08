"use client";

import { ChevronDownIcon, CircleAlertIcon, CircleCheckIcon, CircleHelpIcon, LoaderCircleIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type {
  DotamindActivityItem,
  DotamindConnectionStatus,
  DotamindMessageRunMetadata,
  DotamindToolActivity,
} from "@/lib/assistant-ui/dotamind-run-state";

type RunProcessPanelProps = {
  run: DotamindMessageRunMetadata | null | undefined;
  connectionStatus?: DotamindConnectionStatus | null;
};

type ManualExpansion = "expanded" | "collapsed" | null;

export function RunProcessPanel({ run, connectionStatus }: RunProcessPanelProps) {
  const [manualExpansion, setManualExpansion] = useState<ManualExpansion>(null);

  if (!run || (run.activity.length === 0 && run.omitted_activity_count <= 0)) return null;

  const expanded = manualExpansion === null
    ? run.answer.status !== "ready"
    : manualExpansion === "expanded";
  const connectionEnded = connectionStatus === "ended" ||
    connectionStatus === "cancelled" || connectionStatus === "error";

  return (
    <section className="mb-3 overflow-hidden rounded-xl border bg-muted/25 text-sm" aria-label="处理过程">
      <Button
        type="button"
        variant="ghost"
        className="flex h-auto w-full justify-between rounded-none px-3 py-2 text-left font-medium"
        aria-label="处理过程"
        aria-expanded={expanded}
        onClick={() => setManualExpansion(expanded ? "collapsed" : "expanded")}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span>处理过程</span>
          <span className="truncate text-xs font-normal text-muted-foreground">
            {run.status === "running"
              ? run.stage === "execution" ? "正在处理请求" : "正在生成回答"
              : run.status === "completed" ? "回答已生成"
              : run.status === "cancelled" ? "已停止"
              : "运行失败"}
          </span>
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className={`size-4 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </Button>

      {expanded && (
        <div className="border-t px-3 py-2">
          <ol className="flex flex-col gap-2" aria-label="运行活动">
            {run.activity.map((activity) => {
              if (activity.kind === "stage") {
                return (
                  <li key={activity.id} data-testid={`activity-${activity.id}`} className="flex items-center gap-2 text-muted-foreground">
                    <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
                    <span>{activity.stage === "execution" ? "开始处理请求" : "开始生成回答"}</span>
                  </li>
                );
              }
              if (activity.kind === "commentary") {
                return <CommentaryActivityRow key={activity.id} activity={activity} />;
              }
              return (
                <ToolActivityRow
                  key={activity.id}
                  activity={activity}
                  isConnectionEnded={connectionEnded}
                  runStatus={run.status}
                />
              );
            })}
          </ol>
          {run.omitted_activity_count > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              另有 {run.omitted_activity_count} 条较早活动未展示
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function CommentaryActivityRow({
  activity,
}: {
  activity: Extract<DotamindActivityItem, { kind: "commentary" }>;
}) {
  return (
    <li data-testid={`activity-${activity.id}`} className="min-w-0">
      <p className="whitespace-pre-wrap break-words">{activity.text}</p>
      {activity.truncated && (
        <p className="mt-1 text-xs text-muted-foreground">内容已截断</p>
      )}
    </li>
  );
}

function ToolActivityRow({
  activity,
  isConnectionEnded,
  runStatus,
}: {
  activity: DotamindToolActivity;
  isConnectionEnded: boolean;
  runStatus: DotamindMessageRunMetadata["status"];
}) {
  const stillRunning = activity.status === "running" && !isConnectionEnded && runStatus === "running";
  let statusLabel: string;
  let StatusIcon = CircleHelpIcon;

  if (activity.status === "completed") {
    StatusIcon = CircleCheckIcon;
    const duration = formatDuration(activity.duration_seconds);
    statusLabel = duration ? `已完成 · ${duration}` : "已完成";
  } else if (activity.status === "failed") {
    StatusIcon = CircleAlertIcon;
    statusLabel = activity.error_code ? `失败（${activity.error_code}）` : "失败";
  } else if (stillRunning) {
    StatusIcon = LoaderCircleIcon;
    statusLabel = "进行中";
  } else {
    statusLabel = "结果未确认";
  }

  return (
    <li data-testid={`activity-${activity.id}`} className="flex min-w-0 items-center gap-2">
      <StatusIcon
        aria-hidden="true"
        data-testid={stillRunning ? "tool-running-icon" : undefined}
        className={`size-4 shrink-0 ${stillRunning ? "animate-spin text-muted-foreground" : "text-muted-foreground"}`}
      />
      <span className="min-w-0 flex-1 truncate">调用 {activity.tool_name}</span>
      <span data-testid={`tool-status-${activity.id}`} className="shrink-0 text-xs text-muted-foreground">
        {statusLabel}
      </span>
    </li>
  );
}

function formatDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 1) return `${Math.round(seconds * 1000)} 毫秒`;
  return `${seconds.toFixed(1)} 秒`;
}
