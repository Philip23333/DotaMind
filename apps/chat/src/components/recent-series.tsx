"use client";

import { Button } from "@/components/ui/button";
import { getRecentSeries, type RecentSeriesCandidate, type RecentSeriesResponse } from "@/lib/home-api";
import { useCallback, useEffect, useRef, useState, type FC } from "react";

const REFRESH_AFTER_MS = 600_000;

export type RecentSeriesViewState = {
  response: RecentSeriesResponse | null;
  loading: boolean;
  error: boolean;
};

export type RecentSeriesState = RecentSeriesViewState & {
  retry: () => void;
  refreshOnOpen: () => void;
};

export function useRecentSeries(): RecentSeriesState {
  const [state, setState] = useState<RecentSeriesViewState>({
    response: null,
    loading: false,
    error: false,
  });
  const mounted = useRef(false);
  const lastSuccessAt = useRef<number | null>(null);
  const requestRef = useRef<Promise<void> | null>(null);

  const load = useCallback(() => {
    if (requestRef.current) return requestRef.current;

    setState((previous) => ({ ...previous, loading: true, error: false }));

    const request = getRecentSeries()
      .then((response) => {
        if (!mounted.current) return;
        lastSuccessAt.current = Date.now();
        setState({ response, loading: false, error: false });
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
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const refreshOnOpen = useCallback(() => {
    const response = state.response;
    if (
      state.error ||
      !response ||
      response.status === "stale" ||
      response.status === "unavailable" ||
      lastSuccessAt.current === null ||
      Date.now() - lastSuccessAt.current >= REFRESH_AFTER_MS
    ) {
      void load();
    }
  }, [load, state.error, state.response]);

  return {
    ...state,
    retry: () => void load(),
    refreshOnOpen,
  };
}

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
        return (
          <li key={series.series_id}>
            <button
              type="button"
              className="flex w-full min-w-0 items-start gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-55"
              aria-label={`${series.lifecycle === "running" ? "进行中" : "已结束"}，${displayName(series)}，${details}`}
              disabled={disabled}
              onClick={() => onSelect(series)}
            >
              <span className="mt-0.5 shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                {series.lifecycle === "running" ? "进行中" : "已结束"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block break-words text-sm font-medium">{displayName(series)}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{details}</span>
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

  return (
    <div className="min-w-0 space-y-2">
      {state.loading && !response && (
        <p role="status" className="px-3 py-2 text-sm text-muted-foreground">正在加载近期赛事…</p>
      )}
      {state.error && (
        <StatusWithRetry
          message={response ? "读取失败，仍显示上次可用数据" : "赛事列表暂时不可用"}
          onRetry={onRetry}
        />
      )}
      {!state.error && statusUnavailable && (
        <StatusWithRetry message="赛事列表暂时不可用" onRetry={onRetry} />
      )}
      {!state.error && response?.status === "stale" && (
        <div className="space-y-1 px-3 text-xs text-muted-foreground">
          <p>当前为上次更新的数据</p>
          {response.last_error?.trim() && (
            <StatusWithRetry message="更新暂未成功，可稍后重试" onRetry={onRetry} />
          )}
        </div>
      )}
      {items.length > 0 && <p className="px-3 text-[11px] text-muted-foreground">赛事日期均为北京时间</p>}
      {response?.status === "fresh" && response.items.length > 0 && response.retrieved_at && (
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

type RecentSeriesPanelProps = Omit<RecentSeriesContentProps, "count"> & {
  onOpen: () => void;
};

export const RecentSeriesPanel: FC<RecentSeriesPanelProps> = ({ state, disabled, onSelect, onRetry, onOpen }) => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  const toggle = () => {
    if (open) {
      setOpen(false);
    } else {
      setOpen(true);
      onOpen();
    }
  };

  return (
    <div className="relative mb-2">
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls="recent-series-panel"
        onClick={toggle}
        className="h-8 px-3 text-xs"
      >
        赛事查询
      </Button>
      {open && (
        <section
          id="recent-series-panel"
          aria-label="赛事查询"
          className="absolute inset-x-0 bottom-full z-20 mb-2 max-h-[min(60vh,28rem)] overflow-y-auto rounded-2xl border bg-popover p-3 shadow-lg"
        >
          <h2 className="mb-2 px-3 text-sm font-semibold">🔥最近赛事</h2>
          <RecentSeriesContent
            state={state}
            count={10}
            disabled={disabled}
            onSelect={(series) => {
              onSelect(series);
              setOpen(false);
            }}
            onRetry={onRetry}
          />
        </section>
      )}
    </div>
  );
};

const StatusWithRetry: FC<{ message: string; onRetry: () => void }> = ({ message, onRetry }) => (
  <div className="flex items-center justify-between gap-2 px-3 py-2 text-sm text-muted-foreground">
    <span role="status">{message}</span>
    <button type="button" className="shrink-0 underline underline-offset-2" onClick={onRetry}>重试</button>
  </div>
);

function displayName(series: RecentSeriesCandidate): string {
  return series.name?.trim() || "未命名赛事";
}

function formatSeriesDetails(series: RecentSeriesCandidate): string {
  const start = formatBeijingDate(series.begin_at);
  const end = formatBeijingDate(series.end_at);
  const champion = series.lifecycle === "past" ? series.champion_name?.trim() : "";
  return `${start} ～ ${end}${champion ? `　冠军：${champion}` : ""}`;
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
