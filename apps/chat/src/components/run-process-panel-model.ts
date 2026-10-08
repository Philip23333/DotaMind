import type {
  DotamindActivityItem,
  DotamindCommentaryActivity,
  DotamindToolActivity,
} from "@/lib/assistant-ui/dotamind-run-state";

export type TimelineActivity =
  | { kind: "commentary"; activity: DotamindCommentaryActivity }
  | {
      kind: "tool_group";
      id: string;
      tool_name: string;
      activities: DotamindToolActivity[];
    };

const TOOL_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  "esports.league.search": "联赛查询",
  "esports.series.search": "联赛届次查询",
  "esports.series.teams": "参赛战队查询",
  "esports.tournament.search": "赛事阶段查询",
  "esports.match.search": "对阵查询",
  "esports.team.search": "战队查询",
  "esports.player.search": "职业选手查询",
  "hero.guide": "英雄攻略查询",
  "player.profile": "玩家资料查询",
  "player.recent_games": "玩家近期战绩查询",
  "game.detail": "单局详情查询",
  "catalog.lookup": "游戏资料读取",
  "artifact.grep": "外置结果搜索",
  "artifact.read": "外置结果读取",
  "task.plan": "任务规划",
  "task.checkpoint": "任务进度记录",
  "web.search": "网页搜索",
};

export function getToolDisplayName(toolName: string): string {
  return TOOL_DISPLAY_NAMES[toolName] ?? "工具调用";
}

/** Project display groups without changing the original activity sequence. */
export function groupTimelineActivities(activities: DotamindActivityItem[]): TimelineActivity[] {
  const grouped: TimelineActivity[] = [];
  let adjacentToolGroupIsMergeable = false;

  for (const activity of activities) {
    if (activity.kind === "tool") {
      const previous = adjacentToolGroupIsMergeable ? grouped.at(-1) : undefined;
      if (previous?.kind === "tool_group" && previous.tool_name === activity.tool_name) {
        previous.activities.push(activity);
      } else {
        grouped.push({
          kind: "tool_group",
          id: activity.id,
          tool_name: activity.tool_name,
          activities: [activity],
        });
      }
      adjacentToolGroupIsMergeable = true;
      continue;
    }

    // Stage rows are hidden but remain grouping boundaries.
    adjacentToolGroupIsMergeable = false;
    if (activity.kind === "commentary") {
      grouped.push({ kind: "commentary", activity });
    }
  }

  return grouped;
}

export function formatElapsedSeconds(value: number): string {
  const totalSeconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  if (totalSeconds < 60) return `${totalSeconds}秒`;

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}分${seconds}秒`;
}
