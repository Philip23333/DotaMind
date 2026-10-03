// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecentSeriesState } from "@/components/recent-series";
import { QuickQueryPanels } from "./quick-query-panels";

const recentSeries: RecentSeriesState = {
  response: {
    status: "fresh",
    items: [],
    retrieved_at: "2026-10-03T00:00:00Z",
    last_attempt_at: "2026-10-03T00:00:00Z",
    last_error: null,
  },
  loading: false,
  error: false,
  retry: vi.fn(),
  refreshOnOpen: vi.fn(),
};

function renderPanels(onFill = vi.fn()) {
  return {
    onFill,
    ...render(
      <>
        <QuickQueryPanels
          recentSeries={recentSeries}
          isBusy={false}
          onSelectSeries={vi.fn()}
          onFill={onFill}
        />
        <button type="button">Outside</button>
      </>,
    ),
  };
}

afterEach(() => cleanup());

describe("QuickQueryPanels", () => {
  it("generates hero questions with all positions by default and sorted selected positions", () => {
    const { onFill } = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.change(screen.getByRole("textbox", { name: "英雄名称" }), { target: { value: "  斯温  " } });
    expect(screen.getByRole("button", { name: "选择位置，当前：全部位置" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "填入问题" }));
    expect(onFill).toHaveBeenLastCalledWith("查询英雄斯温的1～5号位攻略");

    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.click(screen.getByRole("button", { name: "选择位置，当前：全部位置" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "2号位" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "4号位" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "5号位" }));
    expect(screen.getByRole("button", { name: "选择位置，当前：1号位、3号位" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "填入问题" }));
    expect(onFill).toHaveBeenLastCalledWith("查询英雄斯温的1号位、3号位攻略");
  });

  it("requires a hero name and at least one position", () => {
    const { onFill } = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.click(screen.getByRole("button", { name: "选择位置，当前：全部位置" }));
    fireEvent.click(screen.getByRole("button", { name: "清空" }));
    fireEvent.click(screen.getByRole("button", { name: "填入问题" }));

    expect(screen.getByText("请输入英雄名称。")).toBeTruthy();
    expect(screen.getByText("至少选择一个位置。")).toBeTruthy();
    expect(onFill).not.toHaveBeenCalled();
  });

  it.each([
    {
      trigger: "玩家战绩",
      label: "Dota 2 好友 ID（Steam32 ID）",
      value: "  76561198012345678  ",
      expected: "查询 Steam32 ID 为76561198012345678的玩家近期战绩",
    },
    {
      trigger: "单局解析",
      label: "比赛 ID",
      value: "000123456789012345678901234567890",
      expected: "分析比赛 ID 为000123456789012345678901234567890的单局详情",
    },
  ])("keeps $trigger identifiers as trimmed decimal strings", ({ trigger, label, value, expected }) => {
    const { onFill } = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: trigger }));
    const textbox = screen.getByRole("textbox", { name: label }) as HTMLInputElement;
    expect(textbox.inputMode).toBe("numeric");
    fireEvent.change(textbox, { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "填入问题" }));
    expect(onFill).toHaveBeenCalledWith(expected);
    expect(onFill).toHaveBeenCalledOnce();
    expect(screen.queryByRole("region", { name: trigger })).toBeNull();
  });

  it.each(["0", "000", "-1", "1.2", "1 2", "12x"]) (
    "rejects non-positive decimal ID text %s without filling the draft",
    (value) => {
      const { onFill } = renderPanels();
      fireEvent.click(screen.getByRole("button", { name: "玩家战绩" }));
      fireEvent.change(screen.getByRole("textbox", { name: "Dota 2 好友 ID（Steam32 ID）" }), {
        target: { value },
      });
      fireEvent.click(screen.getByRole("button", { name: "填入问题" }));
      expect(screen.getByRole("alert").textContent).toBe("请输入有效的 Dota 2 好友 ID。");
      expect(onFill).not.toHaveBeenCalled();
    },
  );

  it("rejects an invalid game ID without filling the draft", () => {
    const { onFill } = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "单局解析" }));
    fireEvent.change(screen.getByRole("textbox", { name: "比赛 ID" }), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "填入问题" }));
    expect(screen.getByRole("alert").textContent).toBe("请输入有效的比赛 ID。");
    expect(onFill).not.toHaveBeenCalled();
  });

  it("keeps panel field state across switching and closing, and only one panel is open", () => {
    renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.change(screen.getByRole("textbox", { name: "英雄名称" }), { target: { value: "敌法师" } });
    fireEvent.click(screen.getByRole("button", { name: "玩家战绩" }));
    expect(screen.queryByRole("region", { name: "英雄攻略" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Dota 2 好友 ID（Steam32 ID）" }), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "单局解析" }));
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    expect((screen.getByRole("textbox", { name: "英雄名称" }) as HTMLInputElement).value).toBe("敌法师");
    expect(screen.getAllByRole("region")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.click(screen.getByRole("button", { name: "玩家战绩" }));
    expect((screen.getByRole("textbox", { name: "Dota 2 好友 ID（Steam32 ID）" }) as HTMLInputElement).value).toBe("12345");
  });

  it("closes on Escape and restores trigger focus; outside clicks close without taking focus", () => {
    const { container } = renderPanels();
    const heroTrigger = screen.getByRole("button", { name: "英雄攻略" });
    fireEvent.click(heroTrigger);
    const heroInput = screen.getByRole("textbox", { name: "英雄名称" });
    fireEvent.pointerDown(heroInput);
    expect(screen.getByRole("region", { name: "英雄攻略" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "英雄攻略" })).toBeNull();
    expect(document.activeElement).toBe(heroTrigger);

    fireEvent.click(heroTrigger);
    const outside = within(container.parentElement ?? document.body).getByRole("button", { name: "Outside" });
    outside.focus();
    fireEvent.pointerDown(outside);
    expect(screen.queryByRole("region", { name: "英雄攻略" })).toBeNull();
    expect(document.activeElement).toBe(outside);
  });

  it("resets form fields after remount instead of persisting them", () => {
    const firstRender = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.change(screen.getByRole("textbox", { name: "英雄名称" }), { target: { value: "斯温" } });
    firstRender.unmount();

    renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    expect((screen.getByRole("textbox", { name: "英雄名称" }) as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("button", { name: "选择位置，当前：全部位置" })).toBeTruthy();
  });

  it("fills on ordinary Enter but leaves IME confirmation Enter to the input method", () => {
    const { onFill } = renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "单局解析" }));
    const input = screen.getByRole("textbox", { name: "比赛 ID" });
    fireEvent.change(input, { target: { value: "123456" } });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 13 });
    expect(onFill).toHaveBeenCalledWith("分析比赛 ID 为123456的单局详情");

    fireEvent.click(screen.getByRole("button", { name: "单局解析" }));
    const reopenedInput = screen.getByRole("textbox", { name: "比赛 ID" });
    fireEvent.keyDown(reopenedInput, { key: "Enter", keyCode: 229, isComposing: true });
    expect(onFill).toHaveBeenCalledOnce();
    expect(screen.getByRole("region", { name: "单局解析" })).toBeTruthy();
  });

  it("uses real checkboxes for position selection and keeps inside clicks open", () => {
    renderPanels();
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    fireEvent.click(screen.getByRole("button", { name: "选择位置，当前：全部位置" }));
    const options = screen.getByRole("group", { name: "位置" });
    const positions = within(options).getAllByRole("checkbox");
    expect(positions).toHaveLength(5);
    fireEvent.click(positions[1]!);
    expect(screen.getByRole("region", { name: "英雄攻略" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "选择位置，当前：1号位、3号位、4号位、5号位" })).toBeTruthy();
  });
});
