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

const backpackItem = {
  item_name_zh: "魔晶",
  item_name_en: "Aghanim's Shard",
  item_image_path: "/api/v1/assets/dota/items/609.png",
};

const neutralItem = {
  item_name_zh: "仙灵榴弹",
  item_name_en: "Faerie Fire",
  item_image_path: "/api/v1/assets/dota/items/237.png",
};

const enhancementItem = {
  item_name_zh: "警觉",
  item_name_en: "Alert",
  item_image_path: "/api/v1/assets/dota/items/1584.png",
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
                tool: "artifact.read",
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

  it("decorates nested game entities in tables, BP lists, and normal lists", () => {
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

  it("uses compact server-projected visual entities without raw tool results", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "# 齐天大圣（Monkey King）英雄介绍" },
      catalog_visual_entities: [
        {
          kind: "hero",
          imagePath: "/api/v1/assets/dota/heroes/114.png",
          label: "齐天大圣",
          names: ["齐天大圣", "Monkey King"],
        },
      ],
    });

    expect(formatted).toContain(
      "# ![齐天大圣](http://localhost:8001/api/v1/assets/dota/heroes/114.png#dota-size=lg)齐天大圣（Monkey King）英雄介绍",
    );
  });

  it("uses Markdown table semantics for horizontal BP and grouped match inventory", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary: [
          "| 顺序 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |",
          "| 选择 | 斯温 | 斯温 | 斯温 | 斯温 | 斯温 | — | — |",
          "| 禁用 | 斯温 | 斯温 | 斯温 | 斯温 | 斯温 | 斯温 | 斯温 |",
          "",
          "| 选手 / 英雄 | K/D/A | 经济 | 装备 |",
          "| --- | --- | --- | --- |",
          "| Yuma · 斯温（24） | 8/2/3 | 22,790 | 主装备：闪烁匕首；背包：魔晶；中立：仙灵榴弹（强化：警觉） |",
        ].join("\n"),
      },
      tool_results: [
        {
          data: {
            players: [
              {
                name: "Yuma",
                ...hero,
                inventory: {
                  main: [item],
                  backpack: [backpackItem],
                  neutral: { item: neutralItem, enhancement: enhancementItem },
                },
              },
            ],
            draft: { draft: [hero] },
          },
        },
      ],
    });

    const heroIcon = "![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=lg)";
    expect(formatted).toContain(`| 选择 | ${Array(5).fill(heroIcon).join(" | ")} | — | — |`);
    expect(formatted).toContain(`| 禁用 | ${Array(7).fill(heroIcon).join(" | ")} |`);
    expect(formatted).not.toContain("| 选择 | 斯温");
    expect(formatted).toContain(
      "| ![斯温](http://localhost:8001/api/v1/assets/dota/heroes/18.png#dota-size=md)Yuma · 斯温（24） |",
    );
    expect(formatted).toContain(
      "主装备：![闪烁匕首](http://localhost:8001/api/v1/assets/dota/items/1.png#dota-size=md)![魔晶](http://localhost:8001/api/v1/assets/dota/items/609.png#dota-size=sm)![仙灵榴弹](http://localhost:8001/api/v1/assets/dota/items/237.png#dota-size=sm)（![警觉](http://localhost:8001/api/v1/assets/dota/items/1584.png#dota-size=sm)）",
    );
    expect(formatted).not.toContain("背包：");
    expect(formatted).not.toContain("中立：");
    expect(formatted).not.toContain("强化：");
  });

  it("keeps purchase paths as inline medium Catalog icons with terminal times", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary:
          "出装路径\n力量腰带 → 护腕 **(03:52)**",
      },
      catalog_visual_entities: [
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/21.png",
          label: "力量腰带",
          names: ["力量腰带", "Belt of Strength"],
        },
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/2.png",
          label: "护腕",
          names: ["护腕", "Bracer"],
        },
      ],
    });

    expect(formatted).toContain(
      "![力量腰带](http://localhost:8001/api/v1/assets/dota/items/21.png#dota-size=md)力量腰带 →",
    );
    expect(formatted).toContain(
      "![护腕](http://localhost:8001/api/v1/assets/dota/items/2.png#dota-size=md)护腕 **(03:52)**",
    );
    expect(formatted).not.toContain("| 相对开局时间 |");
  });

  it("uses large icon-only starting and final equipment while retaining named build paths", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary:
          "## 出装、加点与天赋 · 玩家 · 英雄（12）\n\n**出门装**\n\n仙灵之火 铁树枝干 仙灵之火\n\n**最终装备**\n\n主装备：敏捷便鞋 背包：仙灵之火 中立：铁树枝干（强化：怨灵系带）\n\n**出装路径**\n\n敏捷便鞋 → 怨灵系带 **(03:52)**",
      },
      catalog_visual_entities: [
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/44.png",
          label: "仙灵之火",
          names: ["仙灵之火"],
        },
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/11.png",
          label: "铁树枝干",
          names: ["铁树枝干"],
        },
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/16.png",
          label: "敏捷便鞋",
          names: ["敏捷便鞋"],
        },
        {
          kind: "item",
          imagePath: "/api/v1/assets/dota/items/3.png",
          label: "怨灵系带",
          names: ["怨灵系带"],
        },
      ],
    });

    expect(formatted).toContain(
      "![仙灵之火](http://localhost:8001/api/v1/assets/dota/items/44.png#dota-size=lg)![铁树枝干](http://localhost:8001/api/v1/assets/dota/items/11.png#dota-size=lg)![仙灵之火](http://localhost:8001/api/v1/assets/dota/items/44.png#dota-size=lg)",
    );
    expect(formatted).toContain(
      "![敏捷便鞋](http://localhost:8001/api/v1/assets/dota/items/16.png#dota-size=lg)![仙灵之火](http://localhost:8001/api/v1/assets/dota/items/44.png#dota-size=md)![铁树枝干](http://localhost:8001/api/v1/assets/dota/items/11.png#dota-size=md)![怨灵系带](http://localhost:8001/api/v1/assets/dota/items/3.png#dota-size=md)",
    );
    expect(formatted).toContain(
      "![敏捷便鞋](http://localhost:8001/api/v1/assets/dota/items/16.png#dota-size=md)敏捷便鞋 → ![怨灵系带](http://localhost:8001/api/v1/assets/dota/items/3.png#dota-size=md)怨灵系带 **(03:52)**",
    );
    expect(formatted).not.toContain("#dota-size=lg)仙灵之火");
    expect(formatted).not.toContain("#dota-size=lg)敏捷便鞋");
    expect(formatted).not.toContain("主装备：");
    expect(formatted).not.toContain("背包：");
    expect(formatted).not.toContain("中立：");
    expect(formatted).not.toContain("强化：");
  });

  it("uses medium ability icons only in the player-progress skill sequence", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary:
          "#### 出装、加点与天赋\n\n##### 玩家 · 英雄（12）\n\n**技能加点**\n\n风暴之拳 → 战吼 → 全属性 +2 → 全属性 +2\n\n**天赋选择**\n\n- 10级：+5秒 战吼持续时间",
      },
      catalog_visual_entities: [
        {
          kind: "ability",
          imagePath: "/api/v1/assets/dota/abilities/1.png",
          label: "风暴之拳",
          names: ["风暴之拳"],
        },
        {
          kind: "ability",
          imagePath: "/api/v1/assets/dota/abilities/2.png",
          label: "战吼",
          names: ["战吼"],
        },
      ],
    });

    expect(formatted).toContain(
      "![风暴之拳](http://localhost:8001/api/v1/assets/dota/abilities/1.png#dota-size=md)风暴之拳 → ![战吼](http://localhost:8001/api/v1/assets/dota/abilities/2.png#dota-size=md)战吼 → 全属性 +2 → 全属性 +2",
    );
    expect(formatted).toContain("- 10级：+5秒 战吼持续时间");
  });

  it("renders local team icons without allowing remote image URLs", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: { summary: "# Team Alpha vs Team Beta" },
      catalog_visual_entities: [
        {
          kind: "team",
          imagePath: "/api/v1/assets/esports/teams/1.webp",
          label: "Team Alpha",
          names: ["Team Alpha", "TA"],
        },
        {
          kind: "team",
          imagePath: "/api/v1/assets/esports/teams/2.jpg",
          label: "Team Beta",
          names: ["Team Beta", "TB"],
        },
      ],
    });

    expect(formatted).toContain(
      "![Team Alpha](http://localhost:8001/api/v1/assets/esports/teams/1.webp#dota-size=lg)Team Alpha",
    );
    expect(formatted).toContain(
      "![Team Beta](http://localhost:8001/api/v1/assets/esports/teams/2.jpg#dota-size=lg)Team Beta",
    );
  });

  it("does not decorate a player name from a stale hero visual alias", () => {
    const formatted = formatPlanResponse({
      status: "ok",
      answer: {
        summary: [
          "| 选手 / 英雄 | K/D/A | 经济 | 装备 |",
          "| --- | --- | --- | --- |",
          "| Satanic · 自然先知（27） | 12/2/12 | 39,852 | 主装备： |",
        ].join("\n"),
      },
      catalog_visual_entities: [
        {
          kind: "hero",
          imagePath: "/api/v1/assets/dota/heroes/53.png",
          label: "自然先知",
          names: ["Satanic", "自然先知", "Nature's Prophet"],
        },
      ],
    });

    expect(formatted).toContain(
      "| ![自然先知](http://localhost:8001/api/v1/assets/dota/heroes/53.png#dota-size=md)Satanic · 自然先知（27） |",
    );
    expect(formatted).not.toContain(
      "Satanic · ![自然先知](http://localhost:8001/api/v1/assets/dota/heroes/53.png#dota-size=md)",
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
