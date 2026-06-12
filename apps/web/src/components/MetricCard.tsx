import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone?: "primary" | "accent" | "success";
}

const toneClassName = {
  primary: "bg-[color-mix(in_oklch,var(--color-primary)_12%,white)] text-[var(--color-primary-strong)]",
  accent: "bg-[color-mix(in_oklch,var(--color-accent)_14%,white)] text-[oklch(0.36_0.12_35)]",
  success: "bg-[color-mix(in_oklch,var(--color-success)_14%,white)] text-[oklch(0.32_0.10_150)]",
};

export function MetricCard({ icon: Icon, label, value, detail, tone = "primary" }: MetricCardProps) {
  return (
    <article className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[var(--color-muted)]">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-normal">{value}</p>
        </div>
        <div className={`grid h-9 w-9 place-items-center rounded-md ${toneClassName[tone]}`}>
          <Icon aria-hidden="true" size={18} />
        </div>
      </div>
      <p className="mt-3 text-sm leading-5 text-[var(--color-muted)]">{detail}</p>
    </article>
  );
}
