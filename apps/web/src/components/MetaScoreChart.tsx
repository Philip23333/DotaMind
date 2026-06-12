"use client";

import dynamic from "next/dynamic";
import type { HeroRecommendation } from "@/types/report";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function MetaScoreChart({ heroes }: { heroes: HeroRecommendation[] }) {
  const option = {
    color: ["oklch(0.42 0.11 170)", "oklch(0.58 0.14 35)"],
    grid: { left: 42, right: 16, bottom: 36, top: 24 },
    tooltip: {
      trigger: "axis",
    },
    xAxis: {
      type: "category",
      data: heroes.map((hero) => hero.hero),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "oklch(0.88 0.012 170)" } },
    },
    yAxis: {
      type: "value",
      max: 100,
      axisLabel: { color: "oklch(0.43 0.025 170)" },
      splitLine: { lineStyle: { color: "oklch(0.9 0.012 170)" } },
    },
    series: [
      {
        name: "Meta Score",
        type: "bar",
        barWidth: 28,
        data: heroes.map((hero) => hero.meta_score),
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "Confidence",
        type: "line",
        data: heroes.map((hero) => Math.round(hero.confidence * 100)),
        smooth: true,
        symbolSize: 8,
      },
    ],
  };

  return (
    <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4">
      <div className="mb-3">
        <h2 className="text-lg font-semibold">Score Shape</h2>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Meta score and confidence by hero.
        </p>
      </div>
      <div className="h-72">
        <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />
      </div>
    </section>
  );
}
