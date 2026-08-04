"use client";

import type { PlanStreamEvent } from "@/lib/dotamind-api";
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleAlertIcon,
  LoaderCircleIcon,
  WrenchIcon,
} from "lucide-react";
import { createContext, useContext, useState, type FC, type ReactNode } from "react";

type RunStatus = "running" | "completed" | "failed" | "cancelled";

export type RuntimeTool = Extract<PlanStreamEvent, { type: "tool" }>;

export type RuntimeInfo = {
  messageId: string;
  phase: Extract<PlanStreamEvent, { type: "phase" }>["phase"];
  tools: RuntimeTool[];
  status: RunStatus;
  durationMs?: number;
};

export type RuntimeInfoMap = Record<string, RuntimeInfo>;

const RuntimeInfoContext = createContext<RuntimeInfoMap>({});

export const RuntimeInfoProvider: FC<{ value: RuntimeInfoMap; children: ReactNode }> = ({
  value,
  children,
}) => <RuntimeInfoContext.Provider value={value}>{children}</RuntimeInfoContext.Provider>;

export const useRuntimeInfo = (messageId: string) => useContext(RuntimeInfoContext)[messageId] ?? null;

const phaseLabels: Record<RuntimeInfo["phase"], string> = {
  planning: "分析问题",
  tool_execution: "使用工具",
  answering: "整理回答",
  reviewing: "核验依据",
};

const toolLabels: Record<string, string> = {
  resolve_hero: "识别英雄",
  "stratz.pair_lane_outcome": "查询对线结果",
  "stratz.hero_matchup_ranking": "查询英雄克制数据",
  "stratz.hero_synergy_ranking": "查询英雄配合数据",
  "stratz.lane_meta_global": "查询全局对线数据",
  "stratz.hero_position_stats": "查询位置数据",
  "stratz.hero_daily_trends": "查询每日趋势",
  "stratz.filter_heroes_by_position": "筛选位置英雄",
  "stratz.player_profile": "查询玩家资料",
  "stratz.player_recent_matches": "查询近期比赛",
  "stratz.player_hero_performance": "查询英雄表现",
  "patch.get_records": "查询版本记录",
  "patch.hero_changes": "查询英雄改动",
  "patch.item_changes": "查询物品改动",
  "opendota.resolve_team": "识别战队",
  "opendota.team_recent_matches": "查询战队近期比赛",
  "opendota.team_players": "查询战队阵容",
  "opendota.team_heroes": "查询战队英雄池",
  "opendota.hero_stats_by_role": "查询位置英雄数据",
};

const statusLabel: Record<RunStatus, string> = {
  running: "进行中",
  completed: "已完成",
  failed: "未完成",
  cancelled: "已取消",
};

export const RuntimeInfoCard: FC<{ run: RuntimeInfo }> = ({ run }) => {
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const isOpen = manualOpen ?? run.status !== "completed";
  const completedToolCount = run.tools.filter((tool) => tool.status === "ok").length;
  const isRunning = run.status === "running";

  return (
    <details
      className="mb-4 rounded-xl border bg-muted/35 text-sm"
      open={isOpen}
      onToggle={(event) => setManualOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        {isRunning ? (
          <LoaderCircleIcon className="size-4 animate-spin" />
        ) : run.status === "completed" ? (
          <CheckCircle2Icon className="size-4 text-emerald-600" />
        ) : (
          <CircleAlertIcon className="size-4 text-amber-600" />
        )}
        <span className="font-medium text-foreground">
          {statusLabel[run.status]}
          {run.status === "completed" && ` · 使用 ${completedToolCount} 个工具`}
          {run.durationMs != null && ` · ${(run.durationMs / 1000).toFixed(1)} 秒`}
        </span>
        <ChevronDownIcon className="ml-auto size-4 transition-transform [[open]_&]:rotate-180" />
      </summary>
      <div className="border-t px-3 py-2.5">
        <ol className="space-y-2 text-muted-foreground">
          {Object.entries(phaseLabels).map(([phase, label]) => {
            const reached = Object.keys(phaseLabels).indexOf(phase) <= Object.keys(phaseLabels).indexOf(run.phase);
            return (
              <li key={phase} className={reached ? "text-foreground" : undefined}>
                {reached ? "●" : "○"} {label}
                {phase === run.phase && isRunning ? "…" : ""}
              </li>
            );
          })}
        </ol>
        {run.tools.length > 0 && (
          <div className="mt-3 border-t pt-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-foreground">
              <WrenchIcon className="size-3.5" /> 已使用工具
            </div>
            <ul className="space-y-1 text-muted-foreground">
              {run.tools.map((tool) => (
                <li key={tool.tool_call_id} title={tool.tool}>
                  {tool.status === "running" ? "●" : tool.status === "ok" ? "✓" : "!"}{" "}
                  {toolLabels[tool.tool] ?? tool.tool}
                  {tool.status === "running" ? "…" : ""}
                  {tool.latency_ms != null ? ` · ${tool.latency_ms}ms` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
};
