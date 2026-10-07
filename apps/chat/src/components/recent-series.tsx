"use client";

import {
  getRecentSeries,
  recentSeriesDisplayName,
  refreshRecentSeries,
  type RecentSeriesCandidate,
  type RecentSeriesResponse,
} from "@/lib/home-api";
import { Button } from "@/components/ui/button";
import { useCallback, useEffect, useRef, useState, type FC } from "react";
import { RefreshCwIcon } from "lucide-react";

export type RecentSeriesViewState = {
  response: RecentSeriesResponse | null;
  loading: boolean;
  error: boolean;
  manualRefreshSecondsRemaining: number;
};

export type RecentSeriesState = RecentSeriesViewState & {
  retry: () => void;
};

export function useRecentSeries(): RecentSeriesState {
  const [state, setState] = useState<RecentSeriesViewState>({
    response: null,
    loading: false,
    error: false,
    manualRefreshSecondsRemaining: 0,
  });
  const mounted = useRef(false);
  const requestRef = useRef<Promise<void> | null>(null);
  const cooldownSecondsRef = useRef(0);
  const [cooldownClock, setCooldownClock] = useState<{
    remainingMs: number;
    startedAt: number;
  } | null>(null);

  const load = useCallback((manual = false) => {
    if (requestRef.current) return requestRef.current;

    setState((previous) => ({ ...previous, loading: true, error: false }));

    const request = (manual ? refreshRecentSeries() : getRecentSeries())
      .then((response) => {
        if (!mounted.current) return;
        const remainingMs = getManualRefreshRemainingMs(response);
        const receivedAt = performance.now();
        const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
        cooldownSecondsRef.current = remainingSeconds;
        setCooldownClock(remainingMs > 0 ? { remainingMs, startedAt: receivedAt } : null);
        setState({
          response,
          loading: false,
          error: false,
          manualRefreshSecondsRemaining: remainingSeconds,
        });
      })
      .catch(() => {
        if (!mounted.current) return;
        setState((previous) => ({ ...previous, loading: false, error: true }));
      })
      .finally(() => {
        if (requestRef.current === request) requestRef.current = null;
      });
    requestRef.current = request;
    return request;
  }, []);

  useEffect(() => {
    if (!cooldownClock || cooldownClock.remainingMs <= 0) return;

    const updateCountdown = () => {
      const elapsed = performance.now() - cooldownClock.startedAt;
      const remainingMs = Math.max(0, cooldownClock.remainingMs - elapsed);
      const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
      cooldownSecondsRef.current = remainingSeconds;
      setState((previous) => previous.manualRefreshSecondsRemaining === remainingSeconds
        ? previous
        : { ...previous, manualRefreshSecondsRemaining: remainingSeconds });
      if (remainingSeconds === 0) clearInterval(interval);
    };

    const interval = setInterval(updateCountdown, 1000);
    return () => clearInterval(interval);
  }, [cooldownClock]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const retry = useCallback(() => {
    if (requestRef.current || cooldownSecondsRef.current > 0) return;
    void load(true);
  }, [load]);

  return {
    ...state,
    retry,
  };
}

export const RecentSeriesRefreshButton: FC<{
  loading: boolean;
  cooldownSeconds: number;
  onRefresh: () => void;
}> = ({ loading, cooldownSeconds, onRefresh }) => {
  const label = loading
    ? "正在刷新..."
    : cooldownSeconds > 0
      ? `刷新（剩余 ${cooldownSeconds} 秒）`
      : "刷新";
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={label}
      title={label}
      disabled={loading || cooldownSeconds > 0}
      onClick={onRefresh}
    >
      <RefreshCwIcon className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
      {label}
    </Button>
  );
};

export type RecentSeriesListProps = {
  items: RecentSeriesCandidate[];
  count: number;
  disabled?: boolean;
  onSelect: (series: RecentSeriesCandidate) => void;
};

export const RecentSeriesList: FC<RecentSeriesListProps> = ({ items, count, disabled = false, onSelect }) => {
  const visibleItems = items.slice(0, count);
  if (visibleItems.length === 0) return null;

  return (
    <ul className="flex flex-col gap-1.5">
      {visibleItems.map((series) => {
        const details = formatSeriesDetails(series);
        const fullName = recentSeriesDisplayName(series);
        const running = series.lifecycle === "running";
        return (
          <li key={series.series_id}>
            <button
              type="button"
              className="flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-55"
              aria-label={`${running ? "进行中" : "已结束"}，${fullName}，${details.dates}${details.champion ? `，冠军：${details.champion}` : ""}`}
              title={fullName}
              disabled={disabled}
              onClick={() => onSelect(series)}
            >
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                running ? "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200" : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
              }`}>
                {running ? "进行中" : "已结束"}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{fullName}</span>
              <span className="ml-auto flex shrink-0 flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                <span className="whitespace-nowrap">{formatSeriesDates(series)}</span>
                {details.champion && <span className="whitespace-nowrap">冠军：{details.champion}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
};

export type RecentSeriesContentProps = {
  state: RecentSeriesViewState;
  count: number;
  disabled?: boolean;
  onSelect: (series: RecentSeriesCandidate) => void;
  onRetry: () => void;
};

export const RecentSeriesContent: FC<RecentSeriesContentProps> = ({ state, count, disabled, onSelect, onRetry }) => {
  const { response } = state;
  const items = response?.items ?? [];
  const statusUnavailable = response?.status === "unavailable";
  const retryDisabled = state.loading || state.manualRefreshSecondsRemaining > 0;

  return (
    <div className="min-w-0 space-y-2">
      {state.loading && !response && (
        <p role="status" className="px-3 py-2 text-sm text-muted-foreground">正在加载近期赛事…</p>
      )}
      {state.error && (
        <StatusWithRetry
          message={response ? "读取失败，仍显示上次可用数据" : "赛事列表暂时不可用"}
          onRetry={onRetry}
          disabled={retryDisabled}
        />
      )}
      {!state.error && statusUnavailable && (
        <StatusWithRetry message="赛事列表暂时不可用" onRetry={onRetry} disabled={retryDisabled} />
      )}
      {!state.error && response?.status === "stale" && (
        <div className="space-y-1 px-3 text-xs text-muted-foreground">
          <p>当前为上次更新的数据</p>
          {response.last_error?.trim() && (
            <StatusWithRetry
              message="更新暂未成功，可稍后重试"
              onRetry={onRetry}
              disabled={retryDisabled}
            />
          )}
        </div>
      )}
      {!state.error && response?.status === "fresh" && response.last_error?.trim() && (
        <StatusWithRetry
          message="更新暂未成功，可稍后重试"
          onRetry={onRetry}
          disabled={retryDisabled}
        />
      )}
      {items.length > 0 && <p className="px-3 text-[11px] text-muted-foreground">赛事日期均为北京时间</p>}
      {response?.status === "fresh" && response.retrieved_at && (
        <p className="px-3 text-[11px] text-muted-foreground">
          数据更新于 {formatBeijingDateTime(response.retrieved_at)}（北京时间）
        </p>
      )}
      {items.length === 0 && response?.status === "fresh" && !state.error && (
        <p className="px-3 py-2 text-sm text-muted-foreground">暂无近期赛事</p>
      )}
      {items.length === 0 && response?.status === "stale" && (
        <p className="px-3 py-2 text-sm text-muted-foreground">上次更新时暂无近期赛事</p>
      )}
      {!statusUnavailable && items.length > 0 && (
        <RecentSeriesList items={items} count={count} disabled={disabled} onSelect={onSelect} />
      )}
    </div>
  );
};

const StatusWithRetry: FC<{ message: string; onRetry: () => void; disabled: boolean }> = ({
  message,
  onRetry,
  disabled,
}) => (
  <div className="flex items-center justify-between gap-2 px-3 py-2 text-sm text-muted-foreground">
    <span role="status">{message}</span>
    <button
      type="button"
      className="shrink-0 underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-55"
      disabled={disabled}
      onClick={onRetry}
    >
      重试
    </button>
  </div>
);

function getManualRefreshRemainingMs(response: RecentSeriesResponse): number {
  if (!response.manual_refresh_available_at) return 0;
  const serverTime = Date.parse(response.server_time);
  const allowedAt = Date.parse(response.manual_refresh_available_at);
  if (!Number.isFinite(serverTime) || !Number.isFinite(allowedAt)) return 0;
  return Math.max(0, allowedAt - serverTime);
}

function formatSeriesDetails(series: RecentSeriesCandidate): { dates: string; champion: string | null } {
  const champion = series.lifecycle === "past" ? series.champion_name?.trim() : "";
  return { dates: formatSeriesDates(series), champion: champion || null };
}

function formatSeriesDates(series: RecentSeriesCandidate): string {
  return `${formatBeijingDate(series.begin_at)} ～ ${formatBeijingDate(series.end_at)}`;
}

function formatBeijingDate(value: string | null): string {
  if (!value) return "待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "待定";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const fields = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function formatBeijingDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const fields = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${fields.year}-${fields.month}-${fields.day} ${fields.hour}:${fields.minute}`;
}
