"use client";

import { Button } from "@/components/ui/button";
import {
  RecentSeriesPanel,
  type RecentSeriesState,
} from "@/components/recent-series";
import type { RecentSeriesCandidate } from "@/lib/home-api";
import {
  useEffect,
  useRef,
  useState,
  type FC,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

export type ActiveQuickQueryPanel = "events" | "hero" | "player" | "game" | null;

const POSITIONS = [1, 2, 3, 4, 5] as const;
type Position = (typeof POSITIONS)[number];

type QuickQueryPanelsProps = {
  recentSeries: RecentSeriesState;
  isBusy: boolean;
  onSelectSeries: (series: RecentSeriesCandidate) => void;
  onFill: (text: string) => void;
};

export const QuickQueryPanels: FC<QuickQueryPanelsProps> = ({
  recentSeries,
  isBusy,
  onSelectSeries,
  onFill,
}) => {
  const [activePanel, setActivePanel] = useState<ActiveQuickQueryPanel>(null);
  const [heroName, setHeroName] = useState("");
  const [heroPositions, setHeroPositions] = useState<Position[]>([...POSITIONS]);
  const [positionPickerOpen, setPositionPickerOpen] = useState(false);
  const [heroNameError, setHeroNameError] = useState<string | null>(null);
  const [heroPositionsError, setHeroPositionsError] = useState<string | null>(null);
  const [playerId, setPlayerId] = useState("");
  const [playerIdError, setPlayerIdError] = useState<string | null>(null);
  const [gameId, setGameId] = useState("");
  const [gameIdError, setGameIdError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const eventTriggerRef = useRef<HTMLButtonElement>(null);
  const heroTriggerRef = useRef<HTMLButtonElement>(null);
  const playerTriggerRef = useRef<HTMLButtonElement>(null);
  const gameTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (activePanel === null) return undefined;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || rootRef.current?.contains(target)) return;
      setActivePanel(null);
      setPositionPickerOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      const trigger = {
        events: eventTriggerRef.current,
        hero: heroTriggerRef.current,
        player: playerTriggerRef.current,
        game: gameTriggerRef.current,
      }[activePanel];
      setActivePanel(null);
      setPositionPickerOpen(false);
      trigger?.focus();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [activePanel]);

  const togglePanel = (panel: Exclude<ActiveQuickQueryPanel, "events" | null>) => {
    setActivePanel((current) => current === panel ? null : panel);
    setPositionPickerOpen(false);
  };

  const fill = (text: string) => {
    onFill(text);
    setActivePanel(null);
    setPositionPickerOpen(false);
  };

  const submitHero = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const name = heroName.trim();
    const positions = POSITIONS.filter((position) => heroPositions.includes(position));
    const nameError = name ? null : "请输入英雄名称。";
    const positionsError = positions.length > 0 ? null : "至少选择一个位置。";
    setHeroNameError(nameError);
    setHeroPositionsError(positionsError);
    if (nameError || positionsError) return;

    const positionText = positions.length === POSITIONS.length
      ? "1～5号位"
      : positions.map((position) => `${position}号位`).join("、");
    fill(`查询英雄${name}的${positionText}攻略`);
  };

  const submitPlayer = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const normalized = playerId.trim();
    if (!isPositiveDigitString(normalized)) {
      setPlayerIdError("请输入有效的 Dota 2 好友 ID。");
      return;
    }
    setPlayerIdError(null);
    fill(`查询 Steam32 ID 为${normalized}的玩家近期战绩`);
  };

  const submitGame = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const normalized = gameId.trim();
    if (!isPositiveDigitString(normalized)) {
      setGameIdError("请输入有效的比赛 ID。");
      return;
    }
    setGameIdError(null);
    fill(`分析比赛 ID 为${normalized}的单局详情`);
  };

  const handleTextEnter = (
    event: ReactKeyboardEvent<HTMLInputElement>,
    submit: () => void,
  ) => {
    if (event.key !== "Enter") return;
    const nativeEvent = event.nativeEvent;
    if (nativeEvent.isComposing || nativeEvent.keyCode === 229) return;
    event.preventDefault();
    event.stopPropagation();
    submit();
  };

  const orderedPositions = POSITIONS.filter((position) => heroPositions.includes(position));
  const positionSummary = orderedPositions.length === POSITIONS.length
    ? "全部位置"
    : orderedPositions.map((position) => `${position}号位`).join("、") || "未选择位置";

  return (
    <div ref={rootRef} className="relative mb-2 rounded-xl bg-muted/50 p-2">
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
        <RecentSeriesPanel
          state={recentSeries}
          disabled={isBusy}
          open={activePanel === "events"}
          onOpenChange={(open) => setActivePanel(open ? "events" : null)}
          triggerRef={eventTriggerRef}
          onOpen={recentSeries.refreshOnOpen}
          onRetry={recentSeries.retry}
          onSelect={onSelectSeries}
        />
        <Button
          ref={heroTriggerRef}
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-full bg-muted/75 px-3 text-xs hover:bg-accent aria-expanded:bg-accent"
          aria-expanded={activePanel === "hero"}
          aria-controls="hero-query-panel"
          onClick={() => togglePanel("hero")}
        >
          英雄攻略
        </Button>
        <Button
          ref={playerTriggerRef}
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-full bg-muted/75 px-3 text-xs hover:bg-accent aria-expanded:bg-accent"
          aria-expanded={activePanel === "player"}
          aria-controls="player-query-panel"
          onClick={() => togglePanel("player")}
        >
          玩家战绩
        </Button>
        <Button
          ref={gameTriggerRef}
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-full bg-muted/75 px-3 text-xs hover:bg-accent aria-expanded:bg-accent"
          aria-expanded={activePanel === "game"}
          aria-controls="game-query-panel"
          onClick={() => togglePanel("game")}
        >
          单局解析
        </Button>
      </div>

      {activePanel === "hero" && (
        <section
          id="hero-query-panel"
          role="region"
          aria-label="英雄攻略"
          className="absolute inset-x-0 bottom-full z-20 mb-2 max-h-[min(75vh,35rem)] overflow-y-auto rounded-2xl border bg-popover p-4 shadow-lg"
        >
          <form className="grid gap-4 sm:grid-cols-2" onSubmit={submitHero}>
            <div className="grid content-start gap-2">
              <label htmlFor="quick-hero-name" className="text-sm font-medium">英雄名称</label>
              <input
                id="quick-hero-name"
                type="text"
                value={heroName}
                onChange={(event) => {
                  setHeroName(event.target.value);
                  setHeroNameError(null);
                }}
                onKeyDown={(event) => handleTextEnter(event, () => submitHero())}
                aria-invalid={heroNameError !== null}
                aria-describedby={heroNameError ? "quick-hero-name-error" : undefined}
                className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                placeholder="输入英雄名称"
              />
              {heroNameError && <p id="quick-hero-name-error" role="alert" className="text-xs text-destructive">{heroNameError}</p>}
            </div>

            <div className="grid content-start gap-2">
              <span className="text-sm font-medium">位置</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={`选择位置，当前：${positionSummary}`}
                aria-expanded={positionPickerOpen}
                aria-controls="hero-position-options"
                onClick={() => setPositionPickerOpen((open) => !open)}
                className="justify-between"
              >
                <span>{positionSummary}</span>
                <span aria-hidden="true">⌄</span>
              </Button>
              {positionPickerOpen && (
                <div
                  id="hero-position-options"
                  role="group"
                  aria-label="位置"
                  className="grid gap-2 rounded-md border bg-background p-3"
                >
                  <div className="flex gap-3 text-xs">
                    <button
                      type="button"
                      className="underline underline-offset-2"
                      onClick={() => {
                        setHeroPositions([...POSITIONS]);
                        setHeroPositionsError(null);
                      }}
                    >
                      全选
                    </button>
                    <button
                      type="button"
                      className="underline underline-offset-2"
                      onClick={() => setHeroPositions([])}
                    >
                      清空
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                    {POSITIONS.map((position) => (
                      <label key={position} className="flex items-center gap-1.5 text-xs">
                        <input
                          type="checkbox"
                          checked={heroPositions.includes(position)}
                          aria-label={`${position}号位`}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              event.stopPropagation();
                            }
                          }}
                          onChange={(event) => {
                            setHeroPositions((current) => {
                              const next = event.target.checked
                                ? [...current, position]
                                : current.filter((value) => value !== position);
                              return POSITIONS.filter((value) => next.includes(value));
                            });
                            setHeroPositionsError(null);
                          }}
                        />
                        {position}号位
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {heroPositionsError && <p role="alert" className="text-xs text-destructive">{heroPositionsError}</p>}
            </div>

            <div className="flex justify-end sm:col-span-2">
              <Button type="submit" size="sm">填入问题</Button>
            </div>
          </form>
        </section>
      )}

      {activePanel === "player" && (
        <section
          id="player-query-panel"
          role="region"
          aria-label="玩家战绩"
          className="absolute inset-x-0 bottom-full z-20 mb-2 max-h-[min(75vh,35rem)] overflow-y-auto rounded-2xl border bg-popover p-4 shadow-lg"
        >
          <form className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end" onSubmit={submitPlayer}>
            <div className="grid gap-2">
              <label htmlFor="quick-player-id" className="text-sm font-medium">Dota 2 好友 ID（Steam32 ID）</label>
              <input
                id="quick-player-id"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={playerId}
                onChange={(event) => {
                  setPlayerId(event.target.value);
                  setPlayerIdError(null);
                }}
                onKeyDown={(event) => handleTextEnter(event, () => submitPlayer())}
                aria-invalid={playerIdError !== null}
                aria-describedby={playerIdError ? "quick-player-id-error" : undefined}
                className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                placeholder="输入 Steam32 ID"
              />
              {playerIdError && <p id="quick-player-id-error" role="alert" className="text-xs text-destructive">{playerIdError}</p>}
            </div>
            <Button type="submit" size="sm">填入问题</Button>
          </form>
        </section>
      )}

      {activePanel === "game" && (
        <section
          id="game-query-panel"
          role="region"
          aria-label="单局解析"
          className="absolute inset-x-0 bottom-full z-20 mb-2 max-h-[min(75vh,35rem)] overflow-y-auto rounded-2xl border bg-popover p-4 shadow-lg"
        >
          <form className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end" onSubmit={submitGame}>
            <div className="grid gap-2">
              <label htmlFor="quick-game-id" className="text-sm font-medium">比赛 ID</label>
              <input
                id="quick-game-id"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={gameId}
                onChange={(event) => {
                  setGameId(event.target.value);
                  setGameIdError(null);
                }}
                onKeyDown={(event) => handleTextEnter(event, () => submitGame())}
                aria-invalid={gameIdError !== null}
                aria-describedby={gameIdError ? "quick-game-id-error" : undefined}
                className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                placeholder="输入比赛 ID"
              />
              {gameIdError && <p id="quick-game-id-error" role="alert" className="text-xs text-destructive">{gameIdError}</p>}
            </div>
            <Button type="submit" size="sm">填入问题</Button>
          </form>
        </section>
      )}
    </div>
  );
};

function isPositiveDigitString(value: string): boolean {
  return /^[0-9]+$/.test(value) && /[1-9]/.test(value);
}
