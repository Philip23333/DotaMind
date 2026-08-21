import { describe, expect, it } from "vitest";

import { formatPlanResponse, type PlanResponse } from "./dotamind-api";

const hero = {
  hero_name_zh: "斯温",
  hero_name_en: "Sven",
  hero_image_path: "/api/v1/assets/dota/heroes/18.png",
};

const item = {
  item_name_zh: "闪烁匕首",
  item_name_en: "Blink Dagger",
  item_image_path: "/api/v1/assets/dota/items/1.png",
};

describe("formatPlanResponse", () => {
  it("prefers a stable runtime failure over generic tool execution text", () => {
    const response: PlanResponse = {
      status: "error",
      reason: "tool execution failed",
      error_code: "tool_error",
      runtime: {
        attempts: [
          {
            tool_call_statuses: [
              {
                tool_call_id: "matches",
                tool: "pandascore.list_matches",
                status: "error",
                latency_ms: 0,
                reused: false,
                handler_entered: false,
                dispatch_stage: "reference_resolution",
                failure_code: "reference_resolution_error",
              },
            ],
          },
        ],
      },
    };
    expect(formatPlanResponse(response)).toBe("依赖的上一步结果不可用。");
    expect(formatPlanResponse(response)).not.toContain("tool execution failed");
  });

  it("keeps clarification text unchanged", () => {
    expect(
      formatPlanResponse({
        status: "clarification_required",
        reason: "你想查看哪个赛事或哪支战队的最新战况？",
      }),
    ).toBe("你想查看哪个赛事或哪支战队的最新战况？");
  });

  it("uses a large thumbnail for a single hero title", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "# 齐天大圣（Monkey King）英雄介绍" },
      tool_results: [
        {
          data: {
            hero: {
              name_zh: "齐天大圣",
              name_en: "Monkey King",
              image_path: "/api/v1/assets/dota/heroes/114.png",
            },
          },
        },
      ],
    });

    expect(formatted).toContain(
      "# ![齐天大圣](http://localhost:8001/api/v1/assets/dota/heroes/114.png#dota-size=lg)齐天大圣（Monkey King）英雄介绍",
    );
    expect(formatted).not.toContain("### 相关图片");
  });

  it("uses a large thumbnail for a single item title", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "# 闪烁匕首（Blink Dagger）物品介绍" },
      tool_results: [{ data: { item } }],
    });

    expect(formatted).toContain(
      "# ![闪烁匕首](http://localhost:8001/api/v1/assets/dota/items/1.png#dota-size=lg)闪烁匕首（Blink Dagger）物品介绍",
    );
  });

  it("decorates nested OpenDota entities in tables, BP lists, and normal lists", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary: [
          "# 比赛详情",
          "",
          "## BP 阵容",
          "- 斯温（Sven）",
          "",
          "## 选手表现",
          "- 斯温是一名力量英雄。",
          "",
          "| 选手 | 英雄 | K/D/A |",
          "| --- | --- | --- |",
          "| Yuma | 斯温 | 8/2/3 |",
          "| Ame | 斯温 | 5/4/7 |",
        ].join("\n"),
      },
      tool_results: [
        {
          data: {
            matches: [
              {
                summary: {
                  players: [hero],
                  final_item_details: { item_0: item },
                },
                draft: { draft: [hero] },
              },
            ],
          },
        },
      ],
    });

    expect(formatted).toContain(
      "- ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温（Sven）",
    );
    expect(formatted).toContain(
      "- ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=md)斯温是一名力量英雄。",
    );
    expect(formatted).toContain(
      "| Yuma | ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温 | 8/2/3 |",
    );
    expect(formatted).toContain(
      "| Ame | ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温 | 5/4/7 |",
    );
    expect(formatted).toContain("| --- | --- | --- |");
    expect(formatted.match(/#dota-size=sm/g)).toHaveLength(3);
    expect(formatted.match(/#dota-size=md/g)).toHaveLength(1);
  });

  it("supports item entities nested in match inventory details", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "- 选手购买了闪烁匕首（Blink Dagger）。" },
      tool_results: [
        {
          data: {
            matches: [{ summary: { players: [{ final_item_details: { item_0: item } }] } }],
          },
        },
      ],
    });

    expect(formatted).toContain(
      "- 选手购买了![闪烁匕首](http://localhost:8001/api/v1/assets/dota/items/1.png#dota-size=md)闪烁匕首（Blink Dagger）",
    );
  });

  it("renders an equipment table cell as medium item icons without item names", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary: [
          "| 选手 | 英雄 | K/D/A | 经济 | 装备 |",
          "| --- | --- | --- | --- | --- |",
          "| Yuma | 斯温（24） | 8/2/3 | 22,790 | 闪烁匕首 |",
        ].join("\n"),
      },
      tool_results: [
        {
          data: {
            players: [
              {
                name: "Yuma",
                ...hero,
                final_item_details: { item_0: item },
              },
            ],
          },
        },
      ],
    });

    expect(formatted).toContain(
      "| Yuma | ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温（24） | 8/2/3 | 22,790 | ![闪烁匕首](http://localhost:8001/api/v1/assets/dota/items/1.png#dota-size=md) |",
    );
    expect(formatted).not.toContain(
      "items/1.png#dota-size=md)闪烁匕首",
    );
  });

  it("does not rewrite protected markdown or unsupported responses", () => {
    const answer = [
      "普通介绍：斯温。",
      "`斯温` 不应被替换。",
      "[斯温链接](https://example.test/斯温)",
      "```text",
      "斯温",
      "```",
      "| 英雄 | 结果 |",
      "| --- | --- |",
      "| 斯温 | 胜利 |",
    ].join("\n");
    const response: PlanResponse = {
      status: "ok",
      answer: { summary: answer },
      tool_results: [{ data: { player: hero } }],
    };
    const formatted = formatPlanResponse(response);

    expect(formatted).toContain("`斯温` 不应被替换。");
    expect(formatted).toContain("[斯温链接](https://example.test/斯温)");
    expect(formatted).toContain("```text\n斯温\n```");
    expect(formatted).toContain("| --- | --- |");
    expect(formatted).toContain(
      "| ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温 | 胜利 |",
    );

    expect(
      formatPlanResponse({
        status: "error",
        reason: "执行失败",
        tool_results: [{ data: { player: hero } }],
      }),
    ).toBe("执行失败");
  });

  it("does not treat a player name as a hero alias", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "| 选手 | 英雄 |\n| --- | --- |\n| Yuma | 斯温 |" },
      tool_results: [{ data: { players: [{ name: "Yuma", ...hero }] } }],
    });

    expect(formatted).toContain(
      "| Yuma | ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)斯温 |",
    );
    expect(formatted).not.toContain(
      "| ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=sm)Yuma |",
    );
  });

  it("does not insert thumbnails without a supported image path", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "# 斯温英雄介绍\n\n斯温。" },
      tool_results: [
        {
          data: {
            hero: {
              name_zh: "斯温",
              image_path: "https://cdn.example.test/heroes/18.png",
            },
          },
        },
      ],
    });
    expect(formatted).toBe("# 斯温英雄介绍\n\n斯温。");
  });
});
