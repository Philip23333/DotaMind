// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getRecentSeries, type RecentSeriesCandidate, type RecentSeriesResponse } from "@/lib/home-api";
import {
  RecentSeriesContent,
  RecentSeriesList,
  RecentSeriesPanel,
  type RecentSeriesViewState,
  useRecentSeries,
} from "./recent-series";

vi.mock("@/lib/home-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/home-api")>();
  return { ...actual, getRecentSeries: vi.fn() };
});

const getRecentSeriesMock = vi.mocked(getRecentSeries);

const candidates: RecentSeriesCandidate[] = Array.from({ length: 11 }, (_, index) => ({
  series_id: 100 + index,
  name: index === 1 ? null : `Series ${index + 1}`,
  lifecycle: index === 0 ? "running" : "past",
  begin_at: "2026-09-01T18:00:00Z",
  end_at: index === 0 ? null : "2026-09-10T00:00:00Z",
  champion_name: index === 0 ? "Running result must stay hidden" : index === 2 ? "  Team Example  " : null,
}));

afterEach(() => {
  cleanup();
  getRecentSeriesMock.mockReset();
  vi.restoreAllMocks();
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
  };
}

function viewState(
  result: RecentSeriesResponse | null,
  options: Partial<Pick<RecentSeriesViewState, "loading" | "error">> = {},
): RecentSeriesViewState {
  return { response: result, loading: false, error: false, ...options };
}

describe("RecentSeriesList", () => {
  it("preserves source order, limits the visible count, and formats facts without guessing", () => {
    const onSelect = vi.fn();
    render(<RecentSeriesList items={candidates} count={3} onSelect={onSelect} />);

    expect(screen.getByText("Series 1")).toBeTruthy();
    expect(screen.getByText("未命名赛事")).toBeTruthy();
    expect(screen.getByText("Series 3")).toBeTruthy();
    expect(screen.queryByText("Series 4")).toBeNull();
    expect(screen.getByText("进行中")).toBeTruthy();
    expect(screen.getAllByText("已结束")).toHaveLength(2);
    expect(screen.getByText(/2026-09-02 ～ 待定/)).toBeTruthy();
    expect(screen.getByText(/冠军：Team Example/)).toBeTruthy();
    expect(screen.queryByText(/Running result must stay hidden/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Series 3/ }));
    expect(onSelect).toHaveBeenCalledWith(candidates[2]);
  });

  it("disables event selection while a run is busy", () => {
    render(<RecentSeriesList items={candidates} count={10} disabled onSelect={vi.fn()} />);
    expect((screen.getByRole("button", { name: /^进行中，Series 1，/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("useRecentSeries", () => {
  it("shares its initial request and refreshes fresh data only after 600 seconds", async () => {
    const baseTime = 1_000_000;
    const now = vi.spyOn(Date, "now").mockReturnValue(baseTime);
    getRecentSeriesMock
      .mockResolvedValueOnce(response("fresh"))
      .mockResolvedValueOnce(response("fresh"));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));

    act(() => result.current.refreshOnOpen());
    expect(getRecentSeriesMock).toHaveBeenCalledOnce();

    now.mockReturnValue(baseTime + 600_001);
    act(() => result.current.refreshOnOpen());
    await waitFor(() => expect(getRecentSeriesMock).toHaveBeenCalledTimes(2));
  });

  it.each(["stale", "unavailable"] as const)(
    "refreshes a %s response when the panel opens",
    async (status) => {
      getRecentSeriesMock
        .mockResolvedValueOnce(response(status))
        .mockResolvedValueOnce(response("fresh"));
      const { result } = renderHook(() => useRecentSeries());
      await waitFor(() => expect(result.current.response?.status).toBe(status));

      act(() => result.current.refreshOnOpen());
      await waitFor(() => expect(getRecentSeriesMock).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
    },
  );

  it("retries a failed read when the panel opens", async () => {
    getRecentSeriesMock
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce(response("fresh"));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(result.current.error).toBe(true));

    act(() => result.current.refreshOnOpen());
    await waitFor(() => expect(getRecentSeriesMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
    expect(result.current.error).toBe(false);
  });

  it("reuses an in-flight request when the panel opens", async () => {
    let resolveRead!: (value: RecentSeriesResponse) => void;
    getRecentSeriesMock.mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
    const { result } = renderHook(() => useRecentSeries());
    await waitFor(() => expect(getRecentSeriesMock).toHaveBeenCalledOnce());

    act(() => result.current.refreshOnOpen());
    expect(getRecentSeriesMock).toHaveBeenCalledOnce();
    await act(async () => resolveRead(response("fresh")));
    await waitFor(() => expect(result.current.response?.status).toBe("fresh"));
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
});

describe("RecentSeriesPanel", () => {
  it("opens and closes by toggle or Escape, returns focus to its trigger, and stays open when busy", () => {
    const onOpen = vi.fn();
    const onSelect = vi.fn();
    render(
      <RecentSeriesPanel
        state={viewState(response("fresh"))}
        disabled
        onOpen={onOpen}
        onRetry={vi.fn()}
        onSelect={onSelect}
      />,
    );

    const trigger = screen.getByRole("button", { name: "赛事查询" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(onOpen).toHaveBeenCalledOnce();
    expect(screen.getByRole("region", { name: "赛事查询" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^(进行中|已结束)，/ })).toHaveLength(10);
    expect((screen.getByRole("button", { name: /^进行中，Series 1，/ }) as HTMLButtonElement).disabled).toBe(true);

    act(() => fireEvent.keyDown(document, { key: "Escape" }));
    expect(screen.queryByRole("region", { name: "赛事查询" })).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("selects only from the currently displayed source rows and closes after one selection", () => {
    const onSelect = vi.fn();
    render(
      <RecentSeriesPanel
        state={viewState(response("fresh"))}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "赛事查询" }));
    fireEvent.click(screen.getByRole("button", { name: /^进行中，Series 1，/ }));
    expect(onSelect).toHaveBeenCalledWith(candidates[0]);
    expect(screen.queryByRole("region", { name: "赛事查询" })).toBeNull();
  });
});
