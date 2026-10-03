// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import {
  ComposerModeSwitch,
  composeModeMessage,
  composerModeLabel,
  composerModePlaceholder,
  type ComposerMode,
} from "./composer-mode-switch";

function ModeHarness() {
  const [mode, setMode] = useState<ComposerMode>(null);
  return (
    <>
      <ComposerModeSwitch mode={mode} onChange={setMode} />
      {composerModeLabel(mode) && <p data-testid="mode-label">{composerModeLabel(mode)}</p>}
      <textarea aria-label="消息输入框" placeholder={composerModePlaceholder(mode)} value="原草稿" readOnly />
    </>
  );
}

afterEach(() => cleanup());

describe("ComposerModeSwitch", () => {
  it("toggles a mode without replacing the draft and exposes its label and placeholder", () => {
    render(<ModeHarness />);
    const input = screen.getByRole("textbox", { name: "消息输入框" }) as HTMLTextAreaElement;

    expect(input.placeholder).toBe("询问 Dota 2 电竞赛事、英雄攻略与比赛数据…");
    expect(input.value).toBe("原草稿");
    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));

    expect(screen.getByTestId("mode-label").textContent).toBe("英雄攻略");
    expect(input.placeholder).toBe("输入英雄以及定位，不填定位默认全位置…");
    expect(input.value).toBe("原草稿");
    expect(screen.getByRole("button", { name: "英雄攻略" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "英雄攻略" }));
    expect(screen.queryByTestId("mode-label")).toBeNull();
    expect(input.placeholder).toBe("询问 Dota 2 电竞赛事、英雄攻略与比赛数据…");
    expect(input.value).toBe("原草稿");
  });

  it("keeps the four modes in their fixed order with accessible toggle names", () => {
    render(<ModeHarness />);
    expect(screen.getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual([
      "赛事查询",
      "英雄攻略",
      "玩家战绩",
      "单局解析",
    ]);
    expect(screen.getAllByRole("button").every((button) => button.hasAttribute("aria-pressed"))).toBe(true);
  });
});

describe("composeModeMessage", () => {
  it.each([
    ["events", "赛事查询（以赛事届次 Series 为查询对象）："],
    ["hero", "英雄攻略（未指定位置时默认查询全部位置）："],
    ["player", "玩家战绩（账号使用 Dota 2 好友 ID / Steam32）："],
    ["game", "单局解析（比赛 ID 为 Valve 单局 ID）："],
  ] as const)("adds the %s instruction as plain text and preserves the user's text", (mode, instruction) => {
    const text = "  斯温，1号位\n重点看出装  ";
    expect(composeModeMessage(mode, text)).toBe(`${instruction}\n${text}`);
  });

  it("leaves ordinary and blank input untouched", () => {
    expect(composeModeMessage(null, "原始\n问题")).toBe("原始\n问题");
    expect(composeModeMessage("hero", "  \n ")).toBe("  \n ");
  });
});
