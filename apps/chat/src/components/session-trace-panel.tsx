"use client";

import { Button } from "@/components/ui/button";
import { listSessionTraces, type SessionTraceSummary } from "@/lib/vnext-trace-api";
import { useAuiState } from "@assistant-ui/react";
import { RefreshCwIcon, XIcon } from "lucide-react";
import { useEffect, useState, type FC, type RefObject } from "react";

import { TraceDownloadAction } from "./trace-download-action";

export const SessionTracePanel: FC<{
  browserId?: string;
  open: boolean;
  mobileMode: boolean;
  drawerRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
}> = ({ browserId, open, mobileMode, drawerRef, onClose }) => {
  const sessionId = useAuiState((state) => state.threadListItem.remoteId);
  const [refreshToken, setRefreshToken] = useState(0);
  const [loadResult, setLoadResult] = useState<
    | { key: string; traces: SessionTraceSummary[] }
    | { key: string; error: string }
    | null
  >(null);
  const requestKey = `${browserId ?? ""}:${sessionId ?? ""}:${refreshToken}`;

  useEffect(() => {
    if (!open || !browserId || !sessionId) {
      return;
    }

    const controller = new AbortController();
    void listSessionTraces(browserId, sessionId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setLoadResult({
          key: requestKey,
          traces: [...result]
            .sort(
            (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
            )
            .slice(0, 100),
        });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setLoadResult({
          key: requestKey,
          error: cause instanceof Error ? cause.message : "Trace 列表加载失败。",
        });
      });
    return () => controller.abort();
  }, [browserId, open, requestKey, sessionId]);

  const activeResult = loadResult?.key === requestKey ? loadResult : null;
  const loading = Boolean(open && browserId && sessionId && !activeResult);

  return (
    <>
      {mobileMode && open && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/30"
          aria-label="关闭 Trace 抽屉"
          onClick={onClose}
        />
      )}
      <aside
        ref={drawerRef}
        id="session-trace-drawer"
        className={`chat-trace-surface flex shrink-0 flex-col border-l bg-card ${mobileMode
          ? `fixed inset-y-0 right-0 z-50 w-[min(92vw,24rem)] transition-transform ${open ? "translate-x-0" : "translate-x-full"}`
          : `relative h-full w-[360px] ${open ? "" : "hidden"}`}`}
        aria-label="会话 Trace"
        aria-hidden={!open}
        aria-modal={mobileMode && open ? true : undefined}
        role={mobileMode && open ? "dialog" : undefined}
        inert={!open}
      >
        <header className="flex min-h-16 items-center gap-2 border-b px-3 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">会话 Trace</h2>
            <p className="text-xs text-muted-foreground">最近最多 100 条</p>
          </div>
        {open && sessionId && browserId && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="刷新 Trace 列表"
            title="刷新 Trace 列表"
            disabled={loading}
            onClick={() => setRefreshToken((value) => value + 1)}
          >
            <RefreshCwIcon className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        )}
          <Button type="button" variant="ghost" size="icon" className="size-9" aria-label="关闭会话 Trace" onClick={onClose}>
            <XIcon className="size-4" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          {!sessionId ? (
            <p className="text-sm text-muted-foreground">发送第一条消息后即可查看。</p>
          ) : !browserId ? (
            <p className="text-sm text-muted-foreground">浏览器身份不可用，无法加载 Trace。</p>
          ) : loading ? (
            <p role="status" className="text-sm text-muted-foreground">
              正在加载 Trace…
            </p>
          ) : activeResult && "error" in activeResult ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <p role="alert" className="text-destructive">
                {activeResult.error}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setRefreshToken((value) => value + 1)}
              >
                重试
              </Button>
            </div>
          ) : activeResult && "traces" in activeResult && activeResult.traces.length ? (
            <ul className="divide-y">
              {activeResult.traces.map((trace) => (
                <SessionTraceRow key={trace.trace_id} browserId={browserId!} trace={trace} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              当前会话还没有 Trace。取消记录可能稍后才会出现，可手动刷新。
            </p>
          )}
        </div>
      </aside>
    </>
  );
};

const SessionTraceRow: FC<{ browserId: string; trace: SessionTraceSummary }> = ({
  browserId,
  trace,
}) => (
  <li className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <time dateTime={trace.created_at} className="font-medium">
          {formatTraceTime(trace.created_at)}
        </time>
        <span className="text-muted-foreground">· {statusLabel(trace.status)}</span>
        <span className="text-muted-foreground">· {modeLabel(trace.recording_mode)}</span>
      </div>
      <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
        请求 ID：{trace.request_id}
      </p>
    </div>
    <TraceDownloadAction browserId={browserId} traceId={trace.trace_id} showLabel />
  </li>
);

function statusLabel(status: SessionTraceSummary["status"]): string {
  switch (status) {
    case "completed":
      return "执行完成";
    case "failed":
      return "执行失败";
    case "cancelled":
      return "已取消";
  }
}

function modeLabel(mode: SessionTraceSummary["recording_mode"]): string {
  return mode === "test" ? "测试录制" : "失败诊断";
}

function formatTraceTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
