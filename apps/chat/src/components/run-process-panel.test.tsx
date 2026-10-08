// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunProcessPanel } from "./run-process-panel";
import type {
  DotamindActivityItem,
  DotamindMessageRunMetadata,
  DotamindToolActivity,
} from "@/lib/assistant-ui/dotamind-run-state";

function runState(
  overrides: Partial<DotamindMessageRunMetadata> = {},
): DotamindMessageRunMetadata {
  return {
    request_id: "request-a",
    assistant_message_id: "assistant:request-a",
    status: "running",
    stage: "execution",
    activity: [],
    omitted_activity_count: 0,
    execution_timing: null,
    answer: { attempt_id: "attempt-a", kind: "primary", status: "pending" },
    persistence: "pending",
    error: null,
    ...overrides,
  };
}

function toolActivity(
  overrides: Partial<DotamindToolActivity> = {},
): DotamindToolActivity {
  return {
    kind: "tool",
    id: "tool-1",
    tool_name: "esports.match.search",
    status: "running",
    duration_seconds: null,
    error_code: null,
    ...overrides,
  };
}

function buttonExpanded(): boolean {
  return screen.getByTestId("run-process-toggle").getAttribute("aria-expanded") === "true";
}

function activityRows(): HTMLElement[] {
  return within(screen.getByRole("list", { name: "运行活动" })).getAllByRole("listitem");
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RunProcessPanel", () => {
  it("keeps activity order and merges only adjacent identical tools", () => {
    const activity: DotamindActivityItem[] = [
      { kind: "stage", id: "stage-execution", stage: "execution" },
      toolActivity({ id: "tool-1", status: "completed" }),
      toolActivity({ id: "tool-2", status: "failed", error_code: "provider_timeout" }),
      toolActivity({ id: "tool-3", status: "running" }),
      { kind: "commentary", id: "commentary:1", text: "正在查询赛事。", truncated: false },
      toolActivity({ id: "tool-4", status: "completed" }),
      { kind: "stage", id: "stage-answer", stage: "answer" },
      toolActivity({ id: "tool-5", status: "completed" }),
      toolActivity({ id: "tool-6", status: "completed" }),
      toolActivity({ id: "tool-7", status: "completed" }),
    ];
    render(<RunProcessPanel run={runState({ activity })} />);

    const rows = activityRows();
    expect(rows.map((row) => row.getAttribute("data-testid"))).toEqual([
      "tool-group-tool-1",
      "activity-commentary:1",
      "tool-group-tool-4",
      "tool-group-tool-5",
    ]);
    expect(rows[0]?.textContent).toContain("正在使用对阵查询… · 3次，其中1次失败");
    expect(rows[0]?.textContent).toContain("调用失败（provider_timeout）");
    expect(rows[2]?.textContent).toBe("已使用对阵查询");
    expect(rows[3]?.textContent).toBe("已使用对阵查询 · 3次");
  });

  it("renders commentary as ordinary ordered text with line breaks and truncation notice", () => {
    const commentary = "正在查询职业比赛样本。\n接下来读取攻略详情。";
    render(<RunProcessPanel run={runState({ activity: [
      { kind: "stage", id: "stage-execution", stage: "execution" },
      { kind: "commentary", id: "commentary:1", text: commentary, truncated: true },
      toolActivity(),
    ] })} />);

    const rows = activityRows();
    expect(rows.map((row) => row.getAttribute("data-testid"))).toEqual([
      "activity-commentary:1",
      "tool-group-tool-1",
    ]);
    expect(rows[0]?.querySelector("p")?.textContent).toBe(commentary);
    expect(rows[0]?.querySelector("p")?.className).toContain("whitespace-pre-wrap");
    expect(within(rows[0]!).getByText("内容已截断")).toBeTruthy();
    expect(rows[0]?.textContent).not.toContain("调用");
  });

  it("uses Chinese tool labels and never exposes an unmapped internal name", () => {
    render(<RunProcessPanel run={runState({ activity: [
      toolActivity({ id: "known", tool_name: "esports.series.search" }),
      toolActivity({ id: "unknown", tool_name: "private.internal.endpoint" }),
    ] })} />);

    expect(screen.getByTestId("tool-group-known").textContent).toContain("正在使用联赛届次查询…");
    expect(screen.getByTestId("tool-group-unknown").textContent).toContain("正在使用工具调用…");
    expect(screen.queryByText(/private\.internal\.endpoint/)).toBeNull();
  });

  it("keeps the divider visible whether expanded or collapsed", () => {
    const { container } = render(<RunProcessPanel run={runState({ activity: [toolActivity()] })} />);
    expect(container.querySelector("section")?.className).not.toMatch(/rounded|border\s|bg-muted/);
    expect(container.querySelector(".border-t")).toBeTruthy();

    fireEvent.click(screen.getByTestId("run-process-toggle"));
    expect(buttonExpanded()).toBe(false);
    expect(container.querySelector(".border-t")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "运行活动" })).toBeNull();
  });

  it("shows a live execution timer and freezes on the backend duration in Answer Stage", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-09T02:00:00.000Z"));
    const timing = {
      started_at: "2026-10-09T02:00:00.000Z",
      finished_at: null,
      duration_seconds: null,
    };
    const initial = runState({
      activity: [toolActivity()],
      execution_timing: timing,
    });
    const { rerender } = render(<RunProcessPanel run={initial} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("已处理：0秒");

    act(() => vi.advanceTimersByTime(2_400));
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("已处理：2秒");

    rerender(<RunProcessPanel run={runState({
      ...initial,
      stage: "answer",
      execution_timing: {
        ...timing,
        finished_at: "2026-10-09T02:00:19.200Z",
        duration_seconds: 19.2,
      },
      answer: { ...initial.answer, status: "streaming" },
    })} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("处理用时：19秒");
    expect(buttonExpanded()).toBe(false);

    fireEvent.click(screen.getByTestId("run-process-toggle"));
    expect(buttonExpanded()).toBe(true);
    act(() => vi.advanceTimersByTime(5_000));
    rerender(<RunProcessPanel run={runState({
      ...initial,
      status: "completed",
      stage: "answer",
      execution_timing: {
        ...timing,
        finished_at: "2026-10-09T02:00:19.200Z",
        duration_seconds: 19.2,
      },
      answer: { ...initial.answer, status: "ready" },
      persistence: "saved",
    })} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("处理用时：19秒");
    expect(buttonExpanded()).toBe(true);
  });

  it("formats a minute with a zero-padded seconds part", () => {
    const run = runState({
      status: "completed",
      stage: "answer",
      activity: [toolActivity({ status: "completed" })],
      execution_timing: {
        started_at: "2026-10-09T02:00:00.000Z",
        finished_at: "2026-10-09T02:01:03.900Z",
        duration_seconds: 63.9,
      },
    });
    render(<RunProcessPanel run={run} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("处理用时：1分03秒");
  });

  it("shows terminal execution status with fixed time, without counting the answer stage", () => {
    const run = runState({
      status: "cancelled",
      stage: "execution",
      execution_timing: {
        started_at: "2026-10-09T02:00:00.000Z",
        finished_at: "2026-10-09T02:00:12.900Z",
        duration_seconds: 12.9,
      },
      activity: [toolActivity({ status: "running" })],
    });
    render(<RunProcessPanel run={run} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("已停止 · 用时12秒");
  });

  it("stops the local timer on disconnect and does not invent a duration", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-09T02:00:08.000Z"));
    const run = runState({
      activity: [toolActivity()],
      execution_timing: {
        started_at: "2026-10-09T02:00:00.000Z",
        finished_at: null,
        duration_seconds: null,
      },
    });
    const { rerender } = render(<RunProcessPanel run={run} />);
    act(() => vi.advanceTimersByTime(0));
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("已处理：8秒");

    rerender(<RunProcessPanel run={run} connectionStatus="error" />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("连接中断");
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("连接中断");
    expect(screen.getByTestId("run-process-toggle").textContent).not.toMatch(/\d+秒/);
    expect(screen.getByTestId("tool-group-tool-1").textContent).toContain("结果未确认");
  });

  it("does not fabricate timing for runs without timing data", () => {
    const { rerender } = render(<RunProcessPanel run={runState({ activity: [toolActivity()] })} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("正在处理请求");
    expect(screen.getByTestId("run-process-toggle").textContent).not.toMatch(/\d+秒/);

    rerender(<RunProcessPanel run={runState({
      status: "failed",
      activity: [toolActivity({ status: "failed" })],
    })} />);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain("处理失败");
    expect(screen.getByTestId("run-process-toggle").textContent).not.toMatch(/\d+秒/);
  });

  it("folds on first Answer Stage entry, preserves reopening, and resets for a new request", () => {
    const initial = runState({ activity: [toolActivity()] });
    const { rerender } = render(<RunProcessPanel run={initial} />);
    expect(buttonExpanded()).toBe(true);

    rerender(<RunProcessPanel run={runState({
      ...initial,
      stage: "answer",
      activity: [toolActivity({ status: "completed" })],
      answer: { ...initial.answer, status: "streaming" },
    })} />);
    expect(buttonExpanded()).toBe(false);

    fireEvent.click(screen.getByTestId("run-process-toggle"));
    expect(buttonExpanded()).toBe(true);
    rerender(<RunProcessPanel run={runState({
      ...initial,
      status: "completed",
      stage: "answer",
      activity: [toolActivity({ status: "completed" })],
      answer: { ...initial.answer, status: "ready" },
      persistence: "saved",
    })} />);
    expect(buttonExpanded()).toBe(true);

    rerender(<RunProcessPanel run={runState({
      request_id: "request-b",
      assistant_message_id: "assistant:request-b",
      activity: [toolActivity({ id: "tool-b" })],
    })} />);
    expect(buttonExpanded()).toBe(true);
  });

  it("starts collapsed when first mounted in Answer Stage", () => {
    render(<RunProcessPanel run={runState({
      stage: "answer",
      activity: [toolActivity({ status: "completed" })],
      execution_timing: {
        started_at: "2026-10-09T02:00:00.000Z",
        finished_at: "2026-10-09T02:00:19.000Z",
        duration_seconds: 19,
      },
    })} />);
    expect(buttonExpanded()).toBe(false);
  });

  it.each([
    { status: "cancelled" as const, label: "已停止" },
    { status: "failed" as const, label: "处理失败" },
  ])("does not auto-fold an execution $status", ({ status, label }) => {
    render(<RunProcessPanel run={runState({ status, activity: [toolActivity()] })} />);
    expect(buttonExpanded()).toBe(true);
    expect(screen.getByTestId("run-process-toggle").textContent).toContain(label);
  });

  it("keeps active-tool wording only while running and retains failure information", () => {
    const activity = [
      toolActivity({ id: "tool-1", status: "running" }),
      toolActivity({ id: "tool-2", status: "failed", error_code: "provider_timeout" }),
    ];
    const { rerender } = render(<RunProcessPanel run={runState({ activity })} />);
    expect(screen.getByTestId("tool-group-tool-1").textContent).toContain(
      "正在使用对阵查询… · 2次，其中1次失败",
    );

    rerender(<RunProcessPanel run={runState({
      status: "cancelled",
      activity,
    })} />);
    const row = screen.getByTestId("tool-group-tool-1");
    expect(row.textContent).toContain("对阵查询 · 结果未确认");
    expect(row.textContent).toContain("调用失败（provider_timeout）");
    expect(row.textContent).not.toContain("正在使用");
    expect(row.querySelector(".execution-tool-text")).toBeNull();
  });

  it("preserves omitted-activity count and does not render an empty historical panel", () => {
    render(<RunProcessPanel run={runState({ omitted_activity_count: 7 })} />);
    expect(screen.getByText("另有 7 条较早活动未展示")).toBeTruthy();

    cleanup();
    const { container } = render(<RunProcessPanel run={runState()} />);
    expect(container.querySelector("section")).toBeNull();
  });
});
