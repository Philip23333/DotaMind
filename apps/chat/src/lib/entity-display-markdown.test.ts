import { describe, expect, it } from "vitest";

import {
  displayLinksInMarkdown,
  displayMarkdownForCopy,
  extractDisplayReferences,
} from "@/lib/entity-display-markdown";

const heroRef = "display:valve:hero:14";
const teamRef = "display:pandascore:team:1669";

describe("explicit entity Markdown references", () => {
  it("finds complete references in prose, headings, lists, and GFM tables only", () => {
    const markdown = [
      `## [帕吉](${heroRef})`,
      `- [Team Spirit](${teamRef})`,
      "普通文字 BB 与 Team Spirit 不触发图片。",
      `行内代码 \`[示例](${heroRef})\` 以及代码块：`,
      "```md",
      `[代码示例](${heroRef})`,
      "```",
      "| 实体 | 普通链接 |",
      "| --- | --- |",
      `| [帕吉](${heroRef}) | [官网](https://example.com) |`,
      `[普通链接](https://example.com) ![普通图片](/image.png)`,
    ].join("\n");

    expect(extractDisplayReferences(markdown)).toEqual([heroRef, teamRef]);
    expect(displayLinksInMarkdown(markdown)).toHaveLength(3);
  });

  it("ignores an open streaming link until Markdown closes it", () => {
    expect(extractDisplayReferences(`[帕吉](${heroRef}`)).toEqual([]);
    expect(extractDisplayReferences(`[帕吉](${heroRef})`)).toEqual([heroRef]);
  });

  it("copies labels for resolved, unknown, and malformed references without changing other Markdown", () => {
    const markdown = [
      `对阵：[旧名称](${teamRef}) 与 [未知](${heroRef})。`,
      "```md",
      `[代码里的引用](${heroRef})`,
      "```",
      `[坏引用](display:valve:hero:014) [普通链接](https://example.com) ![图片](/image.png)`,
    ].join("\n");

    expect(displayMarkdownForCopy(markdown, {
      [teamRef]: {
        display_ref: teamRef,
        kind: "team",
        label: "Team Spirit 最新名称",
        image_url: null,
      },
    })).toBe([
      "对阵：Team Spirit 最新名称 与 未知。",
      "```md",
      `[代码里的引用](${heroRef})`,
      "```",
      "坏引用 [普通链接](https://example.com) ![图片](/image.png)",
    ].join("\n"));
    expect(markdown).toContain(`[旧名称](${teamRef})`);
  });
});
