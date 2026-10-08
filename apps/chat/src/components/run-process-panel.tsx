"use client";

import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type {
  DotamindActivityItem,
  DotamindConnectionStatus,
  DotamindMessageRunMetadata,
} from "@/lib/assistant-ui/dotamind-run-state";
import {
  formatElapsedSeconds,
  getToolDisplayName,
  groupTimelineActivities,
  type TimelineActivity,
} from "./run-process-panel-model";

type RunProcessPanelProps = {
  run: DotamindMessageRunMetadata | null | undefined;
  connectionStatus?: DotamindConnectionStatus | null;
};

type ManualExpansion = { requestId: string; expanded: boolean } | null;
type ObservedStage = { requestId: string; stage: DotamindMessageRunMetadata["stage"] } | null;

export function RunProcessPanel({ run, connectionStatus }: RunProcessPanelProps) {
  const [manualExpansion, setManualExpansion] = useState<ManualExpansion>(null);
  const [clockNow, setClockNow] = useState<{ startedAt: string; now: number } | null>(null);
  const observedStage = useRef<ObservedStage>(
    run ? { requestId: run.request_id, stage: run.stage } : null,
  );
  const autoCollapsedRequest = useRef(run?.stage === "answer" ? run.request_id : null);
  const requestId = run?.request_id ?? null;
  const runStage = run?.stage ?? null;

  const connectionEnded = connectionStatus === "ended" ||
    connectionStatus === "cancelled" || connectionStatus === "error";
  const timing = run?.execution_timing;
  const startedAt = timing?.started_at ?? null;
  const canAdvanceClock = Boolean(
    run &&
    run.stage === "execution" &&
    run.status === "running" &&
    !connectionEnded &&
    startedAt &&
    timing?.finished_at === null &&
    timing.duration_seconds === null,
  );

  useEffect(() => {
    if (!requestId || !runStage) {
      observedStage.current = null;
      autoCollapsedRequest.current = null;
      return;
    }

    const previous = observedStage.current;
    if (!previous || previous.requestId !== requestId) {
      observedStage.current = { requestId, stage: runStage };
      autoCollapsedRequest.current = runStage === "answer" ? requestId : null;
      return;
    }

    if (
      previous.stage === "execution" &&
      runStage === "answer" &&
      autoCollapsedRequest.current !== requestId
    ) {
      autoCollapsedRequest.current = requestId;
      setManualExpansion({ requestId, expanded: false });
    }
    observedStage.current = { requestId, stage: runStage };
  }, [requestId, runStage]);

  useEffect(() => {
    if (!canAdvanceClock || !startedAt) {
      return;
    }

    const updateClock = () => setClockNow({ startedAt, now: Date.now() });
    const initialUpdateId = window.setTimeout(updateClock, 0);
    const intervalId = window.setInterval(updateClock, 1000);
    return () => {
      window.clearTimeout(initialUpdateId);
      window.clearInterval(intervalId);
    };
  }, [canAdvanceClock, startedAt]);

  const displayActivities = run ? groupTimelineActivities(run.activity) : [];
  if (
    !run ||
    (displayActivities.length === 0 &&
      run.omitted_activity_count <= 0 &&
      run.execution_timing === null)
  ) {
    return null;
  }

  const requestExpansion = manualExpansion?.requestId === run.request_id
    ? manualExpansion.expanded
    : run.stage !== "answer";
  const expanded = requestExpansion;
  const startedAtMs = startedAt === null ? null : Date.parse(startedAt);
  const elapsedSeconds = canAdvanceClock && startedAt !== null && startedAtMs !== null && Number.isFinite(startedAtMs)
    ? Math.max(0, Math.floor(((clockNow?.startedAt === startedAt ? clockNow.now : startedAtMs) - startedAtMs) / 1000))
    : null;
  const headerText = getHeaderText({
    run,
    connectionEnded,
    elapsedSeconds,
  });

  return (
    <section className="mb-3 min-w-0 text-sm" aria-label="处理过程">
      <button
        type="button"
        className="flex h-auto w-full min-w-0 items-center justify-start gap-2 border-0 bg-transparent px-0 py-1.5 text-left text-sm font-medium text-foreground hover:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        aria-label={`${expanded ? "收起" : "展开"}处理过程，${headerText}`}
        aria-expanded={expanded}
        aria-controls={`run-process-${run.request_id}`}
        data-testid="run-process-toggle"
        onClick={() => setManualExpansion({ requestId: run.request_id, expanded: !expanded })}
      >
        <span className="min-w-0 max-w-full truncate">{headerText}</span>
        {expanded
          ? <ChevronDownIcon aria-hidden="true" className="size-4 shrink-0" />
          : <ChevronRightIcon aria-hidden="true" className="size-4 shrink-0" />}
      </button>

      <div className="border-t border-border/60" aria-hidden="true" />

      <div
        id={`run-process-${run.request_id}`}
        className="min-w-0 pt-2"
        hidden={!expanded}
      >
        {displayActivities.length > 0 && (
          <ol className="flex min-w-0 flex-col gap-2" aria-label="运行活动">
            {displayActivities.map((activity) => activity.kind === "commentary"
              ? <CommentaryActivityRow key={activity.activity.id} activity={activity.activity} />
              : <ToolActivityGroupRow
                  key={activity.id}
                  group={activity}
                  connectionEnded={connectionEnded}
                  runStatus={run.status}
                />)}
          </ol>
        )}
        {run.omitted_activity_count > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            另有 {run.omitted_activity_count} 条较早活动未展示
          </p>
        )}
      </div>
    </section>
  );
}

function getHeaderText({
  run,
  connectionEnded,
  elapsedSeconds,
}: {
  run: DotamindMessageRunMetadata;
  connectionEnded: boolean;
  elapsedSeconds: number | null;
}): string {
  const duration = run.execution_timing?.duration_seconds;
  const formattedDuration = typeof duration === "number" ? formatElapsedSeconds(duration) : null;

  if (run.stage === "answer" && formattedDuration !== null) {
    return `处理用时：${formattedDuration}`;
  }

  if (run.stage === "execution" && formattedDuration !== null) {
    if (run.status === "cancelled") return `已停止 · 用时${formattedDuration}`;
    if (run.status === "failed") return `处理失败 · 用时${formattedDuration}`;
    if (run.status === "completed") return `处理用时：${formattedDuration}`;
  }

  if (connectionEnded && duration == null) return "连接中断";
  if (run.stage === "execution") {
    if (run.status === "cancelled") return "已停止";
    if (run.status === "failed") return "处理失败";
    if (run.status === "completed") return "处理完成";
    return elapsedSeconds === null ? "正在处理请求" : `已处理：${formatElapsedSeconds(elapsedSeconds)}`;
  }

  if (run.status === "cancelled") return "已停止";
  if (run.status === "failed") return "处理失败";
  if (run.status === "completed") return "处理完成";
  return "正在生成回答";
}

function CommentaryActivityRow({
  activity,
}: {
  activity: Extract<DotamindActivityItem, { kind: "commentary" }>;
}) {
  return (
    <li data-testid={`activity-${activity.id}`} className="min-w-0 break-words">
      <p className="whitespace-pre-wrap break-words">{activity.text}</p>
      {activity.truncated && (
        <p className="mt-1 text-xs text-muted-foreground">内容已截断</p>
      )}
    </li>
  );
}

function ToolActivityGroupRow({
  group,
  connectionEnded,
  runStatus,
}: {
  group: Extract<TimelineActivity, { kind: "tool_group" }>;
  connectionEnded: boolean;
  runStatus: DotamindMessageRunMetadata["status"];
}) {
  const name = getToolDisplayName(group.tool_name);
  const failureCount = group.activities.filter((activity) => activity.status === "failed").length;
  const hasRunning = group.activities.some((activity) => activity.status === "running");
  const unconfirmed = hasRunning && (connectionEnded || runStatus !== "running");
  const running = hasRunning && !unconfirmed;
  const countLabel = group.activities.length > 1
    ? failureCount > 0
      ? ` · ${group.activities.length}次，其中${failureCount}次失败`
      : ` · ${group.activities.length}次`
    : "";

  let statusLabel: string;
  if (unconfirmed) statusLabel = `${name} · 结果未确认`;
  else if (running) statusLabel = `正在使用${name}…`;
  else if (failureCount > 0) statusLabel = `${name}失败`;
  else statusLabel = `已使用${name}`;

  const failures = group.activities.filter((activity) => activity.status === "failed");

  return (
    <li data-testid={`tool-group-${group.id}`} className="min-w-0 break-words text-muted-foreground">
      <p className={running ? "execution-tool-text" : undefined}>
        {statusLabel}{countLabel}
      </p>
      {failures.map((activity) => (
        <p key={activity.id} className="mt-0.5 break-words text-xs text-destructive">
          调用失败{activity.error_code ? `（${activity.error_code}）` : ""}
        </p>
      ))}
    </li>
  );
}
