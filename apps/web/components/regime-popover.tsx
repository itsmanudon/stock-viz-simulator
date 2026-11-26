"use client";

import { Popover } from "radix-ui";

import type { MarketRegime } from "@/lib/api/chart-context";
import { formatCloseDate } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";

/**
 * One market's regime badge and its popover: the state, the rules as
 * written (Rule DSL notation over the inputs) with each one's result, the
 * inputs' current values and the as-of date. Descriptive, never advice.
 */

const DOT: Record<string, string> = {
  "Calm trend": "var(--list-lime)",
  Choppy: "var(--list-amber)",
  "High-vol down": "var(--list-pink)",
};

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function inputValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "unknown";
  if (name === "breadth_200") return `${NUMBER.format(value)}%`;
  if (name === "vol_pct_20") return `${NUMBER.format(value)}th pct`;
  return NUMBER.format(value);
}

function resultWord(met: boolean | null | undefined): string {
  return met === true ? "met" : met === false ? "not met" : "unknown";
}

export function RegimePopover({
  market,
  method,
  disclaimer,
}: {
  market: MarketRegime;
  method: string;
  disclaimer: string;
}) {
  const state = market.state ?? "Unknown";
  const date = market.as_of ? formatCloseDate(market.as_of) : null;
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={`${market.name} market regime: ${state}. Show the rules`}
          className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border-muted px-2 text-2xs whitespace-nowrap text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
          data-testid={`regime-badge-${market.market}`}
          data-state={market.state ?? "unknown"}
        >
          <span
            aria-hidden
            className="size-1.5 rounded-full"
            style={
              market.state
                ? { background: DOT[market.state] }
                : { outline: "1px solid currentColor", outlineOffset: -1 }
            }
          />
          <span className="font-medium text-foreground">{market.market}</span>
          <span className="hidden md:inline">{state}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-50 w-[min(24rem,calc(100vw-1.5rem))] rounded-md border border-border bg-surface-elevated p-4 text-xs shadow-lg outline-none"
          data-testid={`regime-popover-${market.market}`}
        >
          <p className="text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
            {market.name} Market Regime
          </p>
          <p className="mt-1 text-sm font-semibold text-foreground">{state}</p>
          <p className="mt-0.5 text-text-tertiary">
            {market.index_name} ({market.index}){date ? `, as of ${date}` : ""}
            {market.reason ? `. ${market.reason}` : ""}
          </p>

          <h3 className="mt-3 text-2xs font-semibold text-text-secondary">Rules, read in order</h3>
          <ol className="mt-1 space-y-1.5">
            {market.rules.map((rule) => (
              <li key={rule.state} data-testid="regime-rule">
                <span className="font-medium text-foreground">{rule.state}</span>{" "}
                <span className="text-text-tertiary">({resultWord(rule.met)})</span>
                <code className="mt-0.5 block font-mono text-2xs break-words text-text-secondary">
                  {rule.rule}
                </code>
              </li>
            ))}
          </ol>

          <h3 className="mt-3 text-2xs font-semibold text-text-secondary">Inputs now</h3>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {market.inputs.map((input) => (
              <div key={input.name} className="contents" title={input.description}>
                <dt className="font-mono text-2xs text-text-secondary">{input.name}</dt>
                <dd
                  className="font-mono text-2xs text-foreground"
                  data-testid={`regime-input-${input.name}`}
                >
                  {inputValue(input.name, input.value)}
                  {input.name === "breadth_200" && market.breadth_universe ? (
                    <span className="text-text-tertiary">
                      {" "}
                      ({market.breadth_count} of {market.breadth_universe})
                    </span>
                  ) : null}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 leading-4 text-text-tertiary">{method}</p>
          <p className="mt-1.5 leading-4 text-text-tertiary">{disclaimer}</p>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
