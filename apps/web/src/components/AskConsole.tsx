"use client";

import { Search, SendHorizonal } from "lucide-react";
import { useState } from "react";

const quickPrompts = [
  "Strongest offlane heroes",
  "Patch impact on carry",
  "Team Spirit form",
  "Verify Beastmaster claim",
];

export function AskConsole() {
  const [query, setQuery] = useState("I play position 3. Which heroes should I practice?");

  return (
    <section
      aria-labelledby="ask-heading"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
    >
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 id="ask-heading" className="text-2xl font-semibold tracking-normal sm:text-3xl">
            Ask MetaMind
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--color-muted)]">
            Query patch impact, hero recommendations, team reports, or evidence checks.
          </p>
        </div>
        <span className="inline-flex w-fit items-center rounded-full bg-[color-mix(in_oklch,var(--color-primary)_12%,white)] px-3 py-1 text-xs font-medium text-[var(--color-primary-strong)]">
          Dota2 MVP
        </span>
      </div>

      <div className="flex flex-col gap-3 md:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Question</span>
          <Search
            aria-hidden="true"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]"
            size={18}
          />
          <input
            className="h-12 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] pl-10 pr-4 text-sm text-[var(--color-ink)] transition placeholder:text-[color-mix(in_oklch,var(--color-muted)_80%,black)] hover:border-[color-mix(in_oklch,var(--color-primary)_45%,var(--color-border))]"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Analyze the strongest offlane heroes in current Dota2 patch."
            value={query}
          />
        </label>
        <button
          className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[var(--color-primary)] px-4 text-sm font-semibold text-white transition hover:bg-[var(--color-primary-strong)]"
          type="button"
        >
          <SendHorizonal aria-hidden="true" size={18} />
          Run sample
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {quickPrompts.map((prompt) => (
          <button
            className="rounded-full border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 text-xs font-medium text-[var(--color-muted)] transition hover:border-[color-mix(in_oklch,var(--color-primary)_45%,var(--color-border))] hover:text-[var(--color-ink)]"
            key={prompt}
            onClick={() => setQuery(prompt)}
            type="button"
          >
            {prompt}
          </button>
        ))}
      </div>
    </section>
  );
}
