// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getRecentSeries,
  refreshRecentSeries,
  type RecentSeriesCandidate,
  type RecentSeriesResponse,
} from "@/lib/home-api";
import {
  RecentSeriesContent,
  RecentSeriesList,
  RecentSeriesRefreshButton,
  type RecentSeriesViewState,
  useRecentSeries,
} from "./recent-series";

vi.mock("@/lib/home-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/home-api")>();
  return {
    ...actual,
    getRecentSeries: vi.fn(),
    refreshRecentSeries: vi.fn(),
  };
});

const getRecentSeriesMock = vi.mocked(getRecentSeries);
const refreshRecentSeriesMock = vi.mocked(refreshRecentSeries);

const candidates: RecentSeriesCandidate[] = Array.from({ length: 11 }, (_, index) => ({
  series_id: 100 + index,
  name: index === 1 ? null : `Series ${index + 1}`,
  league_name: index === 2 ? "League Example" : null,
  lifecycle: index === 0 ? "running" : "past",
  begin_at: "2026-09-01T18:00:00Z",
  end_at: index === 0 ? null : "2026-09-10T00:00:00Z",
  champion_name: index === 0 ? "Running result must stay hidden" : index === 2 ? "  Team Example  " : null,
}));

afterEach(() => {
  cleanup();
  getRecentSeriesMock.mockReset();
  refreshRecentSeriesMock.mockReset();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function response(
  status: RecentSeriesResponse["status"],
  items: RecentSeriesCandidate[] = candidates,
  lastError: string | null = null,
): RecentSeriesResponse {
  return {
    status,
    items,
    retrieved_at: "2026-09-10T00:00:00Z",
    last_attempt_at: "2026-09-10T00:00:00Z",
    last_error: lastError,
    server_time: "2026-09-10T00:00:00Z",
    manual_refresh_available_at: null,
  };
}

function viewState(
  result: RecentSeriesResponse | null,
  options: Partial<Pick<
    RecentSeriesViewState,
    "loading" | "error" | "manualRefreshSecondsRemaining"
  >> = {},
): RecentSeriesViewState {
  return {
    response: result,
    loading: false,
    error: false,
    manualRefreshSecondsRemaining: 0,
    ...options,
  };
}

describe("RecentSeriesList", () => {
  it("preserves source order, limits the visible count, and formats facts without guessing", () => {
    const onSelect = vi.fn();
    render(<RecentSeriesList items={candidates} count={3} onSelect={onSelect} />);

    expect(screen.getByText("Series 1")).toBeTruthy();
    expect(screen.getByText("未命名赛事")).toBeTruthy();
    expect(screen.getByText("League Example · Series 3")).toBeTruthy();
    expect(screen.queryByText("Series 4")).toBeNull();
    expect(screen.getByText("进行中")).toBeTruthy();
    expect(screen.getAllByText("已结束")).toHaveLength(2);
    expect(screen.getByText("2026-09-02 ～ 待定")).toBeTruthy();
    expect(screen.getByText("冠军：Team Example")).toBeTruthy();
    expect(screen.queryByText(/Running result must stay hidden/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /League Example · Series 3/ }));
    expect(onSelect).toHaveBeenCalledWith(candidates[2]);
  });

  it("disables event selection while a run is busy", () => {
    render(<RecentSeriesList items={candidates} count={10} disabled onSelect={vi.fn()} />);
    expect((screen.getByRole("button", { name: /^进行中，Series 1，/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("useRecentSeries", () => {
  it("uses GET initially and POST for an explicit refresh", async () => {
    getRecentSeriesMock
      .mockResolvedValueOnce(response("fresh"));
    refreshRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));

    act(() => result.current.retry());
    await waitFor(() => expect(refreshRecentSeriesMock).toHaveBeenCalledOnce());
    expect(getRecentSeriesMock).toHaveBeenCalledOnce();
    expect(refreshRecentSeriesMock).toHaveBeenCalledWith();
  });

  it.each(["stale", "unavailable"] as const)(
    "can refresh a %s response",
    async (status) => {
      getRecentSeriesMock.mockResolvedValueOnce(response(status));
      refreshRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
      const { result } = renderHook(() => useRecentSeries());
      await waitFor(() => expect(result.current.response?.status).toBe(status));

      act(() => result.current.retry());
      await waitFor(() => expect(refreshRecentSeriesMock).toHaveBeenCalledOnce());
      await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
    },
  );

  it("retries a failed read when retry is requested", async () => {
    getRecentSeriesMock
      .mockRejectedValueOnce(new Error("network error"));
    refreshRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(result.current.error).toBe(true));

    act(() => result.current.retry());
    await waitFor(() => expect(refreshRecentSeriesMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
    expect(result.current.error).toBe(false);
  });

  it("reuses an in-flight request when refresh is requested", async () => {
    let resolveRead!: (value: RecentSeriesResponse) => void;
    getRecentSeriesMock.mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(getRecentSeriesMock).toHaveBeenCalledOnce());

    act(() => result.current.retry());
    expect(getRecentSeriesMock).toHaveBeenCalledOnce();
    expect(refreshRecentSeriesMock).not.toHaveBeenCalled();
    await act(async () => resolveRead(response("fresh")));
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
  });

  it("keeps old rows and shows a disabled refreshing button until the POST completes", async () => {
    const updated = response("fresh", candidates, null);
    updated.retrieved_at = "2026-09-10T01:00:00Z";
    updated.server_time = "2026-09-10T01:00:00Z";
    let finishRefresh!: (value: RecentSeriesResponse) => void;
    getRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    refreshRecentSeriesMock.mockImplementationOnce(
      () => new Promise((resolve) => { finishRefresh = resolve; }),
    );

    function RecentSeriesPanel() {
      const state = useRecentSeries();
      return (
        <>
          <RecentSeriesRefreshButton
            loading={state.loading}
            cooldownSeconds={state.manualRefreshSecondsRemaining}
            onRefresh={state.retry}
          />
          <RecentSeriesContent state={state} count={3} onSelect={vi.fn()} onRetry={state.retry} />
        </>
      );
    }

    render(<RecentSeriesPanel />);
    await waitFor(() => expect(screen.getByText("Series 1")).toBeTruthy());
    expect(screen.getByText(/数据更新于 2026-09-10 08:00（北京时间）/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(refreshRecentSeriesMock).toHaveBeenCalledOnce());
    expect(screen.getByText("Series 1")).toBeTruthy();
    const refreshingButton = screen.getByRole("button", { name: "正在刷新..." }) as HTMLButtonElement;
    expect(refreshingButton.disabled).toBe(true);
    expect(refreshingButton.textContent).toContain("正在刷新...");
    expect(refreshingButton.querySelector("svg")?.getAttribute("class")).toContain("animate-spin");

    await act(async () => finishRefresh(updated));
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新" }).textContent).toContain("刷新"));
    expect(screen.getByText("Series 1")).toBeTruthy();
    expect(screen.getByText(/数据更新于 2026-09-10 09:00（北京时间）/)).toBeTruthy();
    expect(refreshRecentSeriesMock).toHaveBeenCalledOnce();
  });

  it("preserves old rows after a network failure during manual refresh", async () => {
    getRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    refreshRecentSeriesMock.mockRejectedValueOnce(new Error("network error"));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.response?.items[0].name).toBe("Series 1");
    expect(refreshRecentSeriesMock).toHaveBeenCalledOnce();
  });

  it("shows a backend-provided failure cooldown and blocks every retry entry", async () => {
    getRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    const failed = response("stale", candidates, "timeout");
    failed.server_time = "2026-09-10T00:10:00Z";
    failed.manual_refresh_available_at = "2026-09-10T00:20:00Z";
    refreshRecentSeriesMock.mockResolvedValueOnce(failed);

    function RecentSeriesPanel() {
      const state = useRecentSeries();
      return (
        <>
          <RecentSeriesRefreshButton
            loading={state.loading}
            cooldownSeconds={state.manualRefreshSecondsRemaining}
            onRefresh={state.retry}
          />
          <RecentSeriesContent state={state} count={3} onSelect={vi.fn()} onRetry={state.retry} />
        </>
      );
    }

    render(<RecentSeriesPanel />);
    await waitFor(() => expect(screen.getByText("Series 1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(screen.getByText("更新暂未成功，可稍后重试")).toBeTruthy());

    const refreshButton = screen.getByRole("button", { name: "刷新（剩余 600 秒）" }) as HTMLButtonElement;
    expect(refreshButton.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "重试" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Series 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(refreshRecentSeriesMock).toHaveBeenCalledOnce();
  });

  it("shows and counts down a GET cooldown from server timestamps, then cleans its timer", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2035-01-01T00:00:00Z"));
    const limited = response("fresh");
    limited.server_time = "2026-09-10T00:00:00Z";
    limited.manual_refresh_available_at = "2026-09-10T00:00:04.100Z";
    getRecentSeriesMock.mockResolvedValueOnce(limited);

    function RecentSeriesPanel() {
      const state = useRecentSeries();
      return (
        <RecentSeriesRefreshButton
          loading={state.loading}
          cooldownSeconds={state.manualRefreshSecondsRemaining}
          onRefresh={state.retry}
        />
      );
    }

    const { unmount } = render(<RecentSeriesPanel />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const initialButton = screen.getByRole("button", { name: "刷新（剩余 5 秒）" }) as HTMLButtonElement;
    expect(initialButton.disabled).toBe(true);
    expect(refreshRecentSeriesMock).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("button", { name: "刷新（剩余 4 秒）" })).toBeTruthy();
    act(() => vi.advanceTimersByTime(4000));
    const availableButton = screen.getByRole("button", { name: "刷新" }) as HTMLButtonElement;
    expect(availableButton.disabled).toBe(false);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the refresh button busy past the cooldown until its request finishes", async () => {
    vi.useFakeTimers();
    let finishRefresh!: (value: RecentSeriesResponse) => void;
    getRecentSeriesMock.mockResolvedValueOnce(response("fresh"));
    refreshRecentSeriesMock.mockImplementationOnce(
      () => new Promise((resolve) => { finishRefresh = resolve; }),
    );

    function RecentSeriesPanel() {
      const state = useRecentSeries();
      return (
        <>
          <RecentSeriesRefreshButton
            loading={state.loading}
            cooldownSeconds={state.manualRefreshSecondsRemaining}
            onRefresh={state.retry}
          />
          <RecentSeriesContent state={state} count={3} onSelect={vi.fn()} onRetry={state.retry} />
        </>
      );
    }

    render(<RecentSeriesPanel />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => vi.advanceTimersByTime(65_000));
    const busyButton = screen.getByRole("button", { name: "正在刷新..." }) as HTMLButtonElement;
    expect(busyButton.disabled).toBe(true);
    expect(refreshRecentSeriesMock).toHaveBeenCalledOnce();

    const finished = response("fresh");
    finished.server_time = "2026-09-10T00:01:05Z";
    await act(async () => finishRefresh(finished));
    expect((screen.getByRole("button", { name: "刷新" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("RecentSeriesContent", () => {
  it("shows initial loading, valid empty, stale, and unavailable states distinctly", () => {
    const retry = vi.fn();
    const { rerender } = render(
      <RecentSeriesContent state={viewState(null, { loading: true })} count={3} onSelect={vi.fn()} onRetry={retry} />,
    );
    expect(screen.getByText("正在加载近期赛事…")).toBeTruthy();

    rerender(<RecentSeriesContent state={viewState(response("fresh", []))} count={3} onSelect={vi.fn()} onRetry={retry} />);
    expect(screen.getByText("暂无近期赛事")).toBeTruthy();

    rerender(<RecentSeriesContent state={viewState(response("stale", [], "timeout"))} count={3} onSelect={vi.fn()} onRetry={retry} />);
    expect(screen.getByText("当前为上次更新的数据")).toBeTruthy();
    expect(screen.getByText("更新暂未成功，可稍后重试")).toBeTruthy();
    expect(screen.getByText("上次更新时暂无近期赛事")).toBeTruthy();

    rerender(<RecentSeriesContent state={viewState(response("unavailable", []))} count={3} onSelect={vi.fn()} onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(screen.getByRole("status").textContent).toBe("赛事列表暂时不可用");
    expect(retry).toHaveBeenCalledOnce();
  });

  it("keeps old candidates visible after a failed reread", () => {
    render(
      <RecentSeriesContent
        state={viewState(response("fresh"), { error: true })}
        count={3}
        onSelect={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole("status").textContent).toBe("读取失败，仍显示上次可用数据");
    expect(screen.getByText("Series 1")).toBeTruthy();
  });

  it("shows a returned stale failure as an update failure instead of success", () => {
    render(
      <RecentSeriesContent
        state={viewState(response("stale", candidates, "timeout"), { loading: false })}
        count={3}
        onSelect={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("当前为上次更新的数据")).toBeTruthy();
    expect(screen.getByText("更新暂未成功，可稍后重试")).toBeTruthy();
    expect(screen.queryByText("数据已更新")).toBeNull();
    expect(screen.getByText("Series 1")).toBeTruthy();
  });

  it("shows a failed refresh even while the retained snapshot is still fresh", () => {
    render(
      <RecentSeriesContent
        state={viewState(response("fresh", candidates, "timeout"))}
        count={3}
        onSelect={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("更新暂未成功，可稍后重试")).toBeTruthy();
    expect(screen.getByText(/数据更新于 2026-09-10 08:00（北京时间）/)).toBeTruthy();
    expect(screen.getByText("Series 1")).toBeTruthy();
  });

  it("shows the retrieved time for a valid empty fresh response", () => {
    render(
      <RecentSeriesContent
        state={viewState(response("fresh", []))}
        count={3}
        onSelect={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("暂无近期赛事")).toBeTruthy();
    expect(screen.getByText(/数据更新于 2026-09-10 08:00（北京时间）/)).toBeTruthy();
  });
});

describe("homepage recent-series list", () => {
  it("renders the first five rows when requested", () => {
    const { container } = render(<RecentSeriesList items={candidates} count={5} onSelect={vi.fn()} />);
    expect(within(container).getAllByRole("button")).toHaveLength(5);
  });
});
