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

/** Where `value` sits between low and high, as a 0-100 percentage. */
export function rangePosition(
  value: number | null,
  low: number | null,
  high: number | null,
): number | null {
  if (value === null || low === null || high === null) return null;
  if (!Number.isFinite(value) || !Number.isFinite(low) || !Number.isFinite(high)) return null;
  if (high <= low) return null;
  const pct = ((value - low) / (high - low)) * 100;
  return Math.min(100, Math.max(0, pct));
}

export function StockMetricsStrip({
  metrics,
  currency,
  rsi,
  latestClose,
}: {
  metrics: BarMetrics;
  currency: string;
  rsi: number | null;
  /** Drives the 52-week range marker; omit to render the range as text only. */
  latestClose?: number | null;
}) {
  const position = rangePosition(latestClose ?? null, metrics.rangeLow, metrics.rangeHigh);

  const items: { label: string; value: string }[] = [
    { label: "Open", value: formatMoney(metrics.open, currency) },
    { label: "High", value: formatMoney(metrics.high, currency) },
    { label: "Low", value: formatMoney(metrics.low, currency) },
    { label: "Previous close", value: formatMoney(metrics.previousClose, currency) },
    { label: "Volume", value: formatVolume(metrics.volume) },
    { label: "RSI 14", value: rsi === null ? "—" : rsi.toFixed(2) },
  ];

  return (
    <section aria-label="Market and technical metrics" className="border-y border-border-muted">
      {/* Uniform cell borders via ring insets rather than per-index border
          arithmetic, which had to be re-derived for every breakpoint. */}
      <dl className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7">
        {items.map((item) => (
          <div
            key={item.label}
            className="min-w-0 px-3 py-3.5 ring-1 ring-border-muted ring-inset sm:px-4"
          >
            <dt className="truncate text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
              {item.label}
            </dt>
            <dd
              className="mt-1 truncate font-mono text-sm font-medium tabular-nums text-foreground"
              title={item.value}
            >
              {item.value}
            </dd>
          </div>
        ))}

        <div className="col-span-2 min-w-0 px-3 py-3.5 ring-1 ring-border-muted ring-inset sm:col-span-4 sm:px-4 xl:col-span-1">
          <dt className="truncate text-3xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
            52-week range
          </dt>
          <dd className="mt-1 min-w-0">
            {metrics.rangeLow === null || metrics.rangeHigh === null ? (
              <span className="font-mono text-sm text-text-tertiary">—</span>
            ) : (
              <>
                <div className="flex items-baseline justify-between gap-2 font-mono text-2xs tabular-nums text-text-secondary">
                  <span className="truncate">{formatMoney(metrics.rangeLow, currency)}</span>
                  <span className="truncate">{formatMoney(metrics.rangeHigh, currency)}</span>
                </div>
                {position === null ? null : (
                  <div
                    className="relative mt-1.5 h-1.5 rounded-full bg-surface-secondary"
                    role="img"
                    aria-label={`Latest close sits ${position.toFixed(0)} percent of the way through the 52-week range`}
                  >
                    <span
                      className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-brand"
                      style={{ left: `${position}%` }}
                    />
                  </div>
                )}
              </>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}
