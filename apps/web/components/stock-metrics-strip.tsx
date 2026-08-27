import type { BarMetrics } from "@/lib/stock-workspace";

function formatMoney(value: number | null, currency: string): string {
  if (value === null) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: currency === "JPY" ? 0 : 2,
      maximumFractionDigits: currency === "JPY" ? 0 : 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function formatVolume(value: number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    minimumFractionDigits: value >= 1_000_000 ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(value);
}

export function StockMetricsStrip({
  metrics,
  currency,
  rsi,
}: {
  metrics: BarMetrics;
  currency: string;
  rsi: number | null;
}) {
  const range =
    metrics.rangeLow === null || metrics.rangeHigh === null
      ? "—"
      : `${formatMoney(metrics.rangeLow, currency)} – ${formatMoney(metrics.rangeHigh, currency)}`;
  const items = [
    ["Open", formatMoney(metrics.open, currency)],
    ["High", formatMoney(metrics.high, currency)],
    ["Low", formatMoney(metrics.low, currency)],
    ["Previous close", formatMoney(metrics.previousClose, currency)],
    ["Volume", formatVolume(metrics.volume)],
    ["52-week range", range],
    ["RSI 14", rsi === null ? "—" : rsi.toFixed(2)],
  ];

  return (
    <section aria-label="Market and technical metrics" className="border-y border-border-muted">
      <dl className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7">
        {items.map(([label, value], index) => (
          <div
            key={label}
            className={`min-w-0 px-3 py-3.5 sm:px-4 ${
              index > 0 ? "border-l border-border-muted" : ""
            } ${index >= 2 ? "border-t border-border-muted sm:border-t-0" : ""} ${
              index >= 4 ? "sm:border-t xl:border-t-0" : ""
            }`}
          >
            <dt className="truncate text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">
              {label}
            </dt>
            <dd
              className="mt-1 truncate font-mono text-xs font-medium tabular-nums text-foreground"
              title={value}
            >
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
