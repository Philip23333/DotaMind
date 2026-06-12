import { BrainCircuit, Trophy } from "lucide-react";
import type { TeamReport } from "@/types/report";

export function TeamReportPanel({ report }: { report: TeamReport }) {
  return (
    <section
      aria-labelledby="team"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
      id="team"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Team Intelligence Report</h2>
          <p className="mt-1 text-sm leading-6 text-[var(--color-muted)]">{report.summary}</p>
        </div>
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[color-mix(in_oklch,var(--color-primary)_12%,white)] text-[var(--color-primary-strong)]">
          <Trophy aria-hidden="true" size={18} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg bg-[var(--color-surface)] p-3">
          <p className="text-xs font-medium text-[var(--color-muted)]">Record</p>
          <p className="mt-2 text-base font-semibold">{report.recent_record}</p>
        </div>
        <div className="rounded-lg bg-[var(--color-surface)] p-3">
          <p className="text-xs font-medium text-[var(--color-muted)]">Adaptation</p>
          <p className="mt-2 text-base font-semibold">{report.patch_adaptation_score}/100</p>
        </div>
        <div className="rounded-lg bg-[var(--color-surface)] p-3">
          <p className="text-xs font-medium text-[var(--color-muted)]">Confidence</p>
          <p className="mt-2 text-base font-semibold">{Math.round(report.confidence * 100)}%</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <TextBlock title="Draft preferences" items={report.draft_preferences} />
        <TextBlock title="Win patterns" items={report.win_patterns} />
      </div>

      <div className="mt-4">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <BrainCircuit aria-hidden="true" size={16} />
          Signature heroes
        </h3>
        <div className="flex flex-wrap gap-2">
          {report.signature_heroes.map((hero) => (
            <span
              className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs font-medium text-[var(--color-muted)]"
              key={hero}
            >
              {hero}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function TextBlock({ items, title }: { items: string[]; title: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="mt-2 space-y-2 text-sm leading-6 text-[var(--color-muted)]">
        {items.map((item) => (
          <li className="border-b border-[var(--color-border)] pb-2 last:border-0" key={item}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
