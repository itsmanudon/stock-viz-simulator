/**
 * A4.2: the "Costs" disclosure. Every fee component a run (or an order)
 * applied, with its rate, the side it is charged on and a link to the
 * document the rate was copied from; the fills priced under each dated
 * version; what was not checked (price bands) and the ADV cap.
 */

import Link from "next/link";

import {
  type CostsOut,
  type FeeComponent,
  type LiquidityOut,
  formatDay,
  sideLabel,
  sourceDated,
  versionRange,
} from "@/lib/fees";

export function FeeComponentRows({ components }: { components: FeeComponent[] }) {
  return (
    <ul className="divide-y divide-border-muted" data-testid="cost-components">
      {components.map((c) => (
        <li key={c.key} className="grid gap-x-3 gap-y-0.5 py-2 sm:grid-cols-[1fr_auto]">
          <span className="font-medium text-foreground">{c.label}</span>
          <span className="font-mono tabular-nums sm:text-right">{c.rate_text}</span>
          <span className="text-text-tertiary">
            {sideLabel(c.side)}
            {c.note ? ` · ${c.note}` : ""}
          </span>
          <a
            href={c.source.url}
            target="_blank"
            rel="noreferrer"
            className="text-text-secondary underline decoration-border underline-offset-2 hover:text-foreground sm:text-right"
            title={sourceDated(c.source)}
          >
            {c.source.title}
            <span className="block text-2xs text-text-tertiary no-underline">
              {sourceDated(c.source)}
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function CostsDisclosure({
  costs,
  liquidity,
  className,
}: {
  costs: CostsOut | null | undefined;
  liquidity?: LiquidityOut | null;
  className?: string;
}) {
  if (!costs) return null;
  const fills = costs.versions.reduce((n, v) => n + (v.fills ?? 0), 0);
  return (
    <details
      className={`rounded-xl border border-border-muted bg-card text-xs leading-5 ${className ?? ""}`}
      data-testid="costs-disclosure"
    >
      <summary className="cursor-pointer px-3 py-2.5 font-medium hover:text-foreground">
        Costs: {costs.label}
        {costs.brokerage ? ` · ${costs.brokerage.label}` : ""}
        {fills ? ` · ${fills} fill${fills === 1 ? "" : "s"}` : ""}
      </summary>
      <div className="space-y-3 border-t border-border-muted px-3 py-3">
        {costs.versions.length === 0 ? (
          <p className="text-text-secondary">
            {costs.schedule === "none"
              ? "No fee schedule: only the commission you set"
              : "No fills, so no fees were charged"}
            {costs.commission_bps ? ` (${costs.commission_bps} bps a fill).` : "."}
          </p>
        ) : (
          costs.versions.map((v) => (
            <section key={v.effective_from} aria-label={`Rates in force ${versionRange(v)}`}>
              <h4 className="font-semibold text-foreground">
                In force {versionRange(v)}
                {v.fills !== null && v.fills !== undefined ? (
                  <span className="font-normal text-text-tertiary">
                    {" "}
                    · {v.fills} fill{v.fills === 1 ? "" : "s"}
                  </span>
                ) : null}
              </h4>
              <FeeComponentRows components={v.components} />
            </section>
          ))
        )}
        {costs.brokerage ? (
          <p>
            <span className="text-text-tertiary">Brokerage:</span> {costs.brokerage.rate_text}
            {costs.brokerage.source ? (
              <>
                {" "}
                (
                <a
                  href={costs.brokerage.source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  {costs.brokerage.source.title}
                </a>
                )
              </>
            ) : null}
            {costs.commission_bps ? `, plus your ${costs.commission_bps} bps commission` : ""}.
          </p>
        ) : null}
        <ul className="space-y-1 text-text-tertiary">
          {costs.fills_before_coverage > 0 && costs.coverage_from ? (
            <li data-testid="costs-before-coverage">
              {costs.fills_before_coverage} fill
              {costs.fills_before_coverage === 1 ? " was" : "s were"} before{" "}
              {formatDay(costs.coverage_from)}, the first date every rate is confirmed: priced at
              the earliest rates on file.
            </li>
          ) : null}
          {costs.price_bands_note ? (
            <li data-testid="price-bands-note">{costs.price_bands_note}</li>
          ) : null}
          {liquidity ? <li data-testid="liquidity-note">{liquidity.note}</li> : null}
          {liquidity && (liquidity.partial_entries > 0 || liquidity.skipped_entries > 0) ? (
            <li>
              {liquidity.partial_entries} entr{liquidity.partial_entries === 1 ? "y" : "ies"} filled
              in part, {liquidity.skipped_entries} skipped by the cap.
            </li>
          ) : null}
          <li>
            Every schedule and its sources:{" "}
            <Link href="/docs/costs" className="underline underline-offset-2">
              Costs and fees
            </Link>
            .
          </li>
        </ul>
      </div>
    </details>
  );
}
