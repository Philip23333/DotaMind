import { Activity, BarChart3, BrainCircuit, CircleDollarSign, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

const navItems = [
  { label: "Meta", icon: BarChart3 },
  { label: "Patch", icon: Activity },
  { label: "Team", icon: BrainCircuit },
  { label: "Verify", icon: ShieldCheck },
  { label: "CAP", icon: CircleDollarSign },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen text-[var(--color-ink)]">
      <header className="sticky top-0 z-20 border-b border-[var(--color-border)] bg-[color-mix(in_oklch,var(--color-bg)_92%,transparent)] backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--color-primary)] text-white">
              <BrainCircuit aria-hidden="true" size={20} />
            </div>
            <div>
              <p className="text-base font-semibold leading-5">MetaMind</p>
              <p className="text-xs leading-4 text-[var(--color-muted)]">
                Composable esports intelligence
              </p>
            </div>
          </div>
          <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <a
                  className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-[var(--color-muted)] transition hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-ink)]"
                  href={`#${item.label.toLowerCase()}`}
                  key={item.label}
                >
                  <Icon aria-hidden="true" size={16} />
                  {item.label}
                </a>
              );
            })}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-8">{children}</main>
    </div>
  );
}
