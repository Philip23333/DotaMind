import { Activity, ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { PatchImpactReport } from "@/types/report";

interface PatchImpactPanelProps {
  report: PatchImpactReport;
}

export function PatchImpactPanel({ report }: PatchImpactPanelProps) {
  return (
    <section
      aria-labelledby="patch"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
      id="patch"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Patch Impact Report</h2>
          <p className="mt-1 text-sm leading-6 text-[var(--color-muted)]">{report.summary}</p>
        </div>
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[color-mix(in_oklch,var(--color-accent)_14%,white)] text-[oklch(0.36_0.12_35)]">
          <Activity aria-hidden="true" size={18} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ReportList icon={ArrowUpRight} items={report.winners} title="Winners" tone="success" />
        <ReportList icon={ArrowDownRight} items={report.losers} title="Losers" tone="danger" />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <SimpleList items={report.item_impacts} title="Item impact" />
        <SimpleList items={report.lineup_trends} title="Lineup trends" />
      </div>
    </section>
  );
}

function ReportList({
  icon: Icon,
  items,
  title,
  tone,
}: {
  icon: typeof ArrowUpRight;
  items: string[];
  title: string;
  tone: "success" | "danger";
}) {
  const className =
    tone === "success"
      ? "bg-[color-mix(in_oklch,var(--color-success)_14%,white)] text-[oklch(0.32_0.10_150)]"
      : "bg-[color-mix(in_oklch,var(--color-danger)_12%,white)] text-[oklch(0.36_0.12_25)]";

  return (
    <div className="rounded-lg bg-[var(--color-surface)] p-3">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <span className={`grid h-7 w-7 place-items-center rounded-md ${className}`}>
          <Icon aria-hidden="true" size={15} />
        </span>
        {title}
      </h3>
      <ul className="space-y-2 text-sm text-[var(--color-muted)]">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function SimpleList({ items, title }: { items: string[]; title: string }) {
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
