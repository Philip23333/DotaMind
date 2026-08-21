import { describe, expect, it } from "vitest";

import { formatPlanResponse, type PlanResponse } from "./dotamind-api";

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

  it("decorates a hero heading with one inline image", () => {
    const response: PlanResponse = {
      status: "ok",
      answer: { summary: "# 齐天大圣（Monkey King）英雄介绍\n\n齐天大圣是一名敏捷英雄。" },
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
    };
    const formatted = formatPlanResponse(response);
    expect(formatted).toContain(
      "# ![齐天大圣](http://localhost:8001/api/v1/assets/dota/heroes/114.png) 齐天大圣（Monkey King）英雄介绍",
    );
    expect(formatted).not.toContain("### 相关图片");
    expect(formatted.match(/\/api\/v1\/assets\/dota\/heroes\/114\.png/g)).toHaveLength(1);
  });

  it("decorates an item heading and deduplicates repeated tool results", () => {
    const response: PlanResponse = {
      status: "ok",
      answer: { summary: "# 闪烁匕首（Blink Dagger）物品介绍" },
      tool_results: [
        {
          data: {
            item: {
              name_zh: "闪烁匕首",
              name_en: "Blink Dagger",
              image_path: "/api/v1/assets/dota/items/1.png",
            },
          },
        },
        {
          data: {
            item: {
              name_zh: "闪烁匕首",
              name_en: "Blink Dagger",
              image_path: "/api/v1/assets/dota/items/1.png",
            },
          },
        },
      ],
    };
    const formatted = formatPlanResponse(response);
    expect(formatted).toContain(
      "# ![闪烁匕首](http://localhost:8001/api/v1/assets/dota/items/1.png) 闪烁匕首（Blink Dagger）物品介绍",
    );
    expect(formatted.match(/\/api\/v1\/assets\/dota\/items\/1\.png/g)).toHaveLength(1);
    expect(formatted).not.toContain("### 相关图片");
  });

  it("keeps an answer unchanged when no heading contains an entity name", () => {
    const response: PlanResponse = {
      status: "ok",
      answer: { summary: "齐天大圣是一名敏捷英雄。" },
      tool_results: [
        {
          data: {
            hero: {
              name_zh: "齐天大圣",
              image_path: "/api/v1/assets/dota/heroes/114.png",
            },
          },
        },
      ],
    };
    expect(formatPlanResponse(response)).toBe("齐天大圣是一名敏捷英雄。");
    expect(formatPlanResponse(response)).not.toContain("相关图片");
  });

  it("does not decorate error responses", () => {
    const response: PlanResponse = {
      status: "error",
      reason: "执行失败",
      tool_results: [
        {
          data: {
            hero: {
              name_zh: "齐天大圣",
              image_path: "/api/v1/assets/dota/heroes/114.png",
            },
          },
        },
      ],
    };
    expect(formatPlanResponse(response)).toBe("执行失败");
    expect(formatPlanResponse(response)).not.toContain("/api/v1/assets/dota/");
  });
});
