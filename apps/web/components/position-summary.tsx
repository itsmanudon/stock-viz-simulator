import type { TicketPosition } from "@/components/contextual-trade-ticket";
import { formatQuantity } from "@/lib/stock-workspace";
import { titleCase } from "@/lib/title-case";

function money(value: number, currency: string, signed = false): string {
  let formatted: string;
  try {
    formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(Math.abs(value));
  } catch {
    formatted = `${currency} ${Math.abs(value).toFixed(2)}`;
  }
  if (!signed || value === 0) return value < 0 ? `-${formatted}` : formatted;
  return `${value > 0 ? "+" : "-"}${formatted}`;
}

function percentage(value: number | null, signed = false): string {
  if (value === null) return "—";
  return `${signed && value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function PositionSummary({
  ticker,
  nativeCurrency,
  displayCurrency,
  position,
}: {
  ticker: string;
  nativeCurrency: string;
  displayCurrency: string;
  position: TicketPosition;
}) {
  const positive = position.unrealizedPnl >= 0;

  return (
    <section aria-labelledby="position-summary-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 id="position-summary-title" className="text-base font-semibold">
            Your {ticker} position
          </h3>
        </div>
        <p
          className={`flex items-center gap-1.5 font-mono text-sm font-semibold ${positive ? "text-positive" : "text-negative"}`}
        >
          <span>{money(position.unrealizedPnl, displayCurrency, true)}</span>
          <span aria-hidden>·</span>
          <span>{percentage(position.returnPct, true)}</span>
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-y border-border-muted py-4 sm:grid-cols-4">
        <Metric label="Quantity" value={formatQuantity(position.quantity)} />
        <Metric label="Average cost" value={money(position.averageCost, nativeCurrency)} />
        <Metric label="Current value" value={money(position.marketValue, displayCurrency)} />
        <Metric label="Portfolio allocation" value={percentage(position.allocationPct)} />
      </dl>
      {position.availableQuantity < position.quantity ? (
        <p className="text-xs text-muted-foreground">
          {formatQuantity(position.availableQuantity)} shares remain available after open orders.
        </p>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-3xs font-semibold tracking-[0.02em] text-text-tertiary">
        {titleCase(label)}
      </dt>
      <dd className="mt-1 font-mono text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}
