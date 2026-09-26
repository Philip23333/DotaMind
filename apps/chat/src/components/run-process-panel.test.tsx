// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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
  return screen.getByRole("button", { name: "处理过程" }).getAttribute("aria-expanded") === "true";
}

function KeyedPanel({ run }: { run: DotamindMessageRunMetadata }) {
  return <RunProcessPanel key={run.request_id} run={run} />;
}

afterEach(() => cleanup());

describe("RunProcessPanel", () => {
  it("renders execution and tool activity in the original array order", () => {
    const activity: DotamindActivityItem[] = [
      { kind: "stage", id: "stage-execution", stage: "execution" },
      toolActivity(),
      { kind: "stage", id: "stage-answer", stage: "answer" },
    ];
    render(<RunProcessPanel run={runState({ activity, stage: "answer" })} />);

    const rows = within(screen.getByRole("list", { name: "运行活动" })).getAllByRole("listitem");
    expect(rows.map((row) => row.getAttribute("data-testid"))).toEqual([
      "activity-stage-execution",
      "activity-tool-1",
      "activity-stage-answer",
    ]);
    expect(rows[0]?.textContent).toContain("开始处理请求");
    expect(rows[1]?.textContent).toContain("调用 esports.match.search");
    expect(rows[2]?.textContent).toContain("开始生成回答");
  });

  it.each([
    { status: "completed" as const, duration_seconds: 0.25, label: "已完成 · 250 毫秒" },
    { status: "failed" as const, duration_seconds: null, error_code: "provider_timeout", label: "失败（provider_timeout）" },
  ])("updates a tool in place when its status becomes $status", ({ status, duration_seconds, error_code, label }) => {
    const { rerender } = render(<RunProcessPanel run={runState({ activity: [toolActivity()] })} />);
    rerender(
      <RunProcessPanel
        run={runState({
          activity: [toolActivity({ status, duration_seconds, error_code: error_code ?? null })],
        })}
      />,
    );

    expect(screen.getAllByTestId("activity-tool-1")).toHaveLength(1);
    expect(screen.getByTestId("tool-status-tool-1").textContent).toBe(label);
  });

  it("reports exactly how many earlier activity items were omitted", () => {
    render(<RunProcessPanel run={runState({ omitted_activity_count: 7 })} />);
    expect(screen.getByText("另有 7 条较早活动未展示")).toBeTruthy();
  });

  it("starts expanded and folds when the answer becomes ready", () => {
    const { rerender } = render(<RunProcessPanel run={runState({ activity: [toolActivity()] })} />);
    expect(buttonExpanded()).toBe(true);

    rerender(<RunProcessPanel run={runState({
      status: "completed",
      stage: "answer",
      activity: [toolActivity({ status: "completed", duration_seconds: 1 })],
      answer: { attempt_id: "attempt-a", kind: "primary", status: "ready" },
      persistence: "saving",
    })} />);
    expect(buttonExpanded()).toBe(false);
  });

  it("keeps a manual expansion through saving and saved metadata updates", () => {
    const ready = runState({
      status: "completed",
      stage: "answer",
      activity: [toolActivity({ status: "completed" })],
      answer: { attempt_id: "attempt-a", kind: "primary", status: "ready" },
      persistence: "saving",
    });
    const { rerender } = render(<RunProcessPanel run={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "处理过程" }));
    expect(buttonExpanded()).toBe(true);

    rerender(<RunProcessPanel run={{ ...ready, persistence: "saved" }} />);
    expect(buttonExpanded()).toBe(true);
  });

  it("keeps an early manual collapse during later activity updates", () => {
    const initial = runState({ activity: [toolActivity()] });
    const { rerender } = render(<RunProcessPanel run={initial} />);
    fireEvent.click(screen.getByRole("button", { name: "处理过程" }));
    expect(buttonExpanded()).toBe(false);

    rerender(<RunProcessPanel run={{
      ...initial,
      activity: [toolActivity(), { kind: "stage", id: "stage-answer", stage: "answer" }],
      stage: "answer",
      answer: { attempt_id: "attempt-a", kind: "primary", status: "streaming" },
    }} />);
    expect(buttonExpanded()).toBe(false);
  });

  it("does not carry one message's manual choice into the next message", () => {
    const first = runState({
      request_id: "request-a",
      answer: { attempt_id: "attempt-a", kind: "primary", status: "ready" },
      activity: [toolActivity()],
    });
    const { rerender } = render(<KeyedPanel run={first} />);
    fireEvent.click(screen.getByRole("button", { name: "处理过程" }));
    expect(buttonExpanded()).toBe(true);

    rerender(<KeyedPanel run={runState({
      request_id: "request-b",
      assistant_message_id: "assistant:request-b",
      answer: { attempt_id: "attempt-b", kind: "primary", status: "ready" },
      activity: [toolActivity({ id: "tool-2" })],
    })} />);
    expect(buttonExpanded()).toBe(false);
  });

  it("stops the running icon and marks unfinished tool results unconfirmed after disconnect", () => {
    const run = runState({ activity: [toolActivity()] });
    const { rerender } = render(<RunProcessPanel run={run} connectionStatus="error" />);
    expect(screen.getByTestId("tool-status-tool-1").textContent).toBe("结果未确认");
    expect(screen.queryByTestId("tool-running-icon")).toBeNull();

    rerender(<RunProcessPanel
      run={{ ...run, status: "cancelled", answer: { ...run.answer, status: "interrupted" } }}
      connectionStatus="cancelled"
    />);
    expect(screen.getByTestId("tool-status-tool-1").textContent).toBe("结果未确认");
    expect(screen.queryByTestId("tool-running-icon")).toBeNull();
  });

  it("does not render an empty panel for a historical message without process data", () => {
    const { container } = render(<RunProcessPanel run={null} />);
    expect(container.querySelector("section")).toBeNull();
  });
});
