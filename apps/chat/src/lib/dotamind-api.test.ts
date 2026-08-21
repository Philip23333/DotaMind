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

  it("renders unique catalog images from tool results", () => {
    const response: PlanResponse = {
      status: "ok",
      answer: { summary: "敌法师是一名敏捷英雄。" },
      tool_results: [
        {
          data: {
            hero: {
              name_zh: "敌法师",
              image_path: "/api/v1/assets/dota/heroes/1.png",
            },
          },
        },
        {
          data: {
            hero: {
              name_zh: "敌法师",
              image_path: "/api/v1/assets/dota/heroes/1.png",
            },
          },
        },
      ],
    };
    const formatted = formatPlanResponse(response);
    expect(formatted).toContain(
      "![敌法师](http://localhost:8001/api/v1/assets/dota/heroes/1.png)",
    );
    expect(formatted.match(/\/api\/v1\/assets\/dota\/heroes\/1\.png/g)).toHaveLength(1);
  });
});
