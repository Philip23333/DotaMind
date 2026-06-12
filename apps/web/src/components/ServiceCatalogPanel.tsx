import { CircleDollarSign, Code2 } from "lucide-react";
import type { ServiceCatalog } from "@/types/report";

export function ServiceCatalogPanel({ catalog }: { catalog: ServiceCatalog }) {
  return (
    <section
      aria-labelledby="cap"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
      id="cap"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Agent API / CAP Service</h2>
          <p className="mt-1 text-sm text-[var(--color-muted)]">{catalog.commerce_status}</p>
        </div>
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[color-mix(in_oklch,var(--color-accent)_14%,white)] text-[oklch(0.36_0.12_35)]">
          <CircleDollarSign aria-hidden="true" size={18} />
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {catalog.services.map((service) => (
          <article
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
            key={service.name}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">{service.name}</h3>
                <p className="mt-1 text-sm leading-5 text-[var(--color-muted)]">
                  {service.description}
                </p>
              </div>
              <span className="rounded-full bg-[var(--color-primary)] px-2 py-1 text-xs font-semibold text-white">
                {service.price_usdc} USDC
              </span>
            </div>
            <div className="mt-3 flex items-center gap-2 rounded-md bg-[var(--color-bg)] px-3 py-2 text-xs font-medium text-[var(--color-muted)]">
              <Code2 aria-hidden="true" size={14} />
              {service.endpoint}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
