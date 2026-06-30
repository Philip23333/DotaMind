"use client";

import { AlertCircle, CheckCircle2, Loader2, Search, SendHorizonal } from "lucide-react";
import { useState } from "react";
import { runExperimentalQuery } from "@/lib/api";
import type { NaturalLanguageQueryResponse } from "@/types/report";

const quickPrompts = [
  "Strongest offlane heroes",
  "Patch impact on carry",
  "Team Spirit form",
  "Verify Beastmaster claim",
];

export function AskConsole() {
  const [query, setQuery] = useState("I play position 3. Which heroes should I practice?");
  const [result, setResult] = useState<NaturalLanguageQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit() {
    const trimmedQuery = query.trim();

    if (!trimmedQuery || isLoading) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await runExperimentalQuery(trimmedQuery);
      setResult(response);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Failed to run v2.1 query.");
    } finally {
      setIsLoading(false);
    }
  }

  const metaResult = result?.result.report_type === "meta_report" ? result.result : null;

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
          className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[var(--color-primary)] px-4 text-sm font-semibold text-white transition hover:bg-[var(--color-primary-strong)] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isLoading}
          onClick={handleSubmit}
          type="button"
        >
          {isLoading ? (
            <Loader2 aria-hidden="true" className="animate-spin" size={18} />
          ) : (
            <SendHorizonal aria-hidden="true" size={18} />
          )}
          Run v2.1 query
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

      <div className="mt-4 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">Pipeline output</h2>
            <p className="mt-0.5 text-xs leading-5 text-[var(--color-muted)]">
              Calls the canonical Orchestrator endpoint and shows the executed pipeline steps.
            </p>
          </div>
          <span className="inline-flex w-fit items-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-1 text-xs font-medium text-[var(--color-muted)]">
            /api/v1/query
          </span>
        </div>

        {error ? (
          <div className="mt-3 flex gap-2 rounded-md border border-[color-mix(in_oklch,var(--color-danger)_35%,var(--color-border))] bg-[color-mix(in_oklch,var(--color-danger)_8%,white)] p-3 text-sm text-[var(--color-danger)]">
            <AlertCircle aria-hidden="true" className="mt-0.5 shrink-0" size={16} />
            <div>
              <p className="font-medium">Query failed</p>
              <p className="mt-1 text-xs leading-5">{error}. Confirm the API is running on port 8000.</p>
            </div>
          </div>
        ) : null}

        {result ? (
          <div className="mt-3 grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
            <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-[var(--color-muted)]">Execution trace</p>
                <span className="rounded-full bg-[color-mix(in_oklch,var(--color-success)_12%,white)] px-2 py-0.5 text-xs font-medium text-[var(--color-success)]">
                  {result.routed_service}
                </span>
              </div>
              <ol className="space-y-2">
                {result.tasks.map((task, index) => (
                  <li className="flex gap-2 text-xs leading-5 text-[var(--color-ink)]" key={`${task.agent}-${index}`}>
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_oklch,var(--color-primary)_12%,white)] text-[11px] font-semibold text-[var(--color-primary-strong)]">
                      {index + 1}
                    </span>
                    <span>
                      <span className="font-semibold">{task.agent}</span>: {task.action}
                    </span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-[var(--color-muted)]">Report sample</p>
                <span className="text-xs text-[var(--color-muted)]">
                  Confidence {Math.round(result.result.confidence * 100)}%
                </span>
              </div>

              {metaResult ? (
                <div className="space-y-2">
                  {metaResult.top_heroes.slice(0, 3).map((hero) => (
                    <div
                      className="grid grid-cols-[1fr_auto] gap-3 rounded-md bg-[var(--color-surface)] px-3 py-2"
                      key={hero.hero}
                    >
                      <div>
                        <p className="text-sm font-semibold text-[var(--color-ink)]">{hero.hero}</p>
                        <p className="mt-0.5 text-xs text-[var(--color-muted)]">
                          WR {(hero.win_rate * 100).toFixed(1)}%, pro {(hero.pro_presence * 100).toFixed(0)}%, evidence {hero.evidence.length}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-semibold text-[var(--color-primary-strong)]">{hero.meta_score}</p>
                        <p className="text-xs text-[var(--color-muted)]">score</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-start gap-2 rounded-md bg-[var(--color-surface)] p-3 text-sm text-[var(--color-muted)]">
                  <CheckCircle2 aria-hidden="true" className="mt-0.5 shrink-0 text-[var(--color-success)]" size={16} />
                  <p>{result.result.summary}</p>
                </div>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--color-muted)]">
            Run a query to inspect the v2.1 Orchestrator, Retriever, Analyzer, Critic, and Formatter path.
          </p>
        )}
      </div>
    </section>
  );
}
