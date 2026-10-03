"use client";

import { Button } from "@/components/ui/button";
import { Compass, ScanSearch, Trophy, UserRoundSearch } from "lucide-react";
import type { FC } from "react";

export type ComposerMode = "events" | "hero" | "player" | "game" | null;

const MODE_COPY = {
  events: {
    label: "赛事查询",
    placeholder: "输入赛事名称或你想了解的赛程、战况…",
    instruction: "赛事查询（以赛事届次 Series 为查询对象）：",
  },
  hero: {
    label: "英雄攻略",
    placeholder: "输入英雄以及定位，不填定位默认全位置…",
    instruction: "英雄攻略（未指定位置时默认查询全部位置）：",
  },
  player: {
    label: "玩家战绩",
    placeholder: "输入 Dota 2 好友 ID（Steam32），可补充查询要求…",
    instruction: "玩家战绩（账号使用 Dota 2 好友 ID / Steam32）：",
  },
  game: {
    label: "单局解析",
    placeholder: "输入比赛 ID，可补充分析要求…",
    instruction: "单局解析（比赛 ID 为 Valve 单局 ID）：",
  },
} as const;

export function composerModePlaceholder(mode: ComposerMode): string {
  return mode === null
    ? "询问 Dota 2 电竞赛事、英雄攻略与比赛数据…"
    : MODE_COPY[mode].placeholder;
}

export function composerModeLabel(mode: ComposerMode): string | null {
  return mode === null ? null : MODE_COPY[mode].label;
}

export function composeModeMessage(mode: ComposerMode, text: string): string {
  if (mode === null || !text.trim()) return text;
  return `${MODE_COPY[mode].instruction}\n${text}`;
}

const MODES = [
  { mode: "events", Icon: Trophy },
  { mode: "hero", Icon: Compass },
  { mode: "player", Icon: UserRoundSearch },
  { mode: "game", Icon: ScanSearch },
] as const;

export const ComposerModeSwitch: FC<{
  mode: ComposerMode;
  onChange: (mode: ComposerMode) => void;
}> = ({ mode, onChange }) => (
  <div className="flex min-w-0 items-center gap-0.5 rounded-full bg-muted/60 p-1" aria-label="查询模式">
    {MODES.map(({ mode: itemMode, Icon }) => {
      const label = MODE_COPY[itemMode].label;
      const selected = mode === itemMode;
      return (
        <Button
          key={itemMode}
          type="button"
          variant="ghost"
          size="icon"
          className={`group relative size-10 shrink-0 rounded-full shadow-sm transition-colors focus-visible:z-50 ${
            selected
              ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
              : "bg-card/80 text-muted-foreground hover:bg-accent hover:text-foreground"
          }`}
          aria-label={label}
          aria-pressed={selected}
          title={label}
          onClick={() => onChange(selected ? null : itemMode)}
        >
          <Icon className="size-5" aria-hidden="true" />
          <span
            role="tooltip"
            className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md bg-foreground px-2 py-1 text-xs text-background opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          >
            {label}
          </span>
        </Button>
      );
    })}
  </div>
);
