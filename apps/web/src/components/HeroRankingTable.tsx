import { ShieldCheck } from "lucide-react";
import type { HeroRecommendation } from "@/types/report";

interface HeroRankingTableProps {
  heroes: HeroRecommendation[];
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export function HeroRankingTable({ heroes }: HeroRankingTableProps) {
  return (
    <section
      aria-labelledby="meta"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)]"
      id="meta"
    >
      <div className="flex flex-col gap-2 border-b border-[var(--color-border)] p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">Meta Report Dashboard</h2>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            Ranked offlane recommendations with evidence status.
          </p>
        </div>
        <span className="inline-flex w-fit items-center gap-2 rounded-full bg-[color-mix(in_oklch,var(--color-success)_14%,white)] px-3 py-1 text-xs font-medium text-[oklch(0.32_0.10_150)]">
          <ShieldCheck aria-hidden="true" size={14} />
          Evidence attached
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead className="bg-[var(--color-surface)] text-xs font-semibold text-[var(--color-muted)]">
            <tr>
              <th className="px-4 py-3">Hero</th>
              <th className="px-4 py-3">Grade</th>
              <th className="px-4 py-3">Meta Score</th>
              <th className="px-4 py-3">Win</th>
              <th className="px-4 py-3">Pick</th>
              <th className="px-4 py-3">Ban</th>
              <th className="px-4 py-3">Pro Presence</th>
              <th className="px-4 py-3">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {heroes.map((hero) => (
              <tr
                className="border-t border-[var(--color-border)] transition hover:bg-[var(--color-surface)]"
                key={hero.hero}
              >
                <td className="px-4 py-4 align-top">
                  <p className="font-semibold">{hero.hero}</p>
                  <p className="mt-1 max-w-sm text-xs leading-5 text-[var(--color-muted)]">
                    {hero.reasons[0]}
                  </p>
                </td>
                <td className="px-4 py-4 align-top">
                  <span className="rounded-md bg-[var(--color-primary)] px-2 py-1 text-xs font-semibold text-white">
                    {hero.recommendation}
                  </span>
                </td>
                <td className="px-4 py-4 align-top font-semibold">{hero.meta_score}</td>
                <td className="px-4 py-4 align-top">{percent(hero.win_rate)}</td>
                <td className="px-4 py-4 align-top">{percent(hero.pick_rate)}</td>
                <td className="px-4 py-4 align-top">{percent(hero.ban_rate)}</td>
                <td className="px-4 py-4 align-top">{percent(hero.pro_presence)}</td>
                <td className="px-4 py-4 align-top">{percent(hero.confidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
