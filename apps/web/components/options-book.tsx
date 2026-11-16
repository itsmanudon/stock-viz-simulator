/**
 * The options book (Phase 9.5): its Greeks in money, and open legs grouped
 * by expiry with what today's close would do. Server component; the figures
 * come from GET /v1/options/book, which states its method.
 */

import type { OptionsBook } from "@/lib/api/options";

function usd(value: number | string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Number(value),
  );
}

function signedUsd(value: number | string): string {
  const n = Number(value);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(Math.abs(n))}`;
}

export function OptionsGreeks({ book }: { book: OptionsBook | null }) {
  if (!book || book.underlyings.length === 0) return null;
  const figures = [
    {
      label: "Dollar delta",
      value: signedUsd(book.dollar_delta),
      hint: "moves like this much stock",
    },
    { label: "Theta", value: `${signedUsd(book.theta_per_day)}/day`, hint: "time decay" },
    { label: "Vega", value: signedUsd(book.vega_per_point), hint: "per 1 point of volatility" },
    { label: "Rho", value: signedUsd(book.rho_per_point), hint: "per 1 point of the rate" },
  ];
  return (
    <section aria-labelledby="options-greeks-heading" className="mb-8">
      <h2 id="options-greeks-heading" className="text-lg font-semibold tracking-tight">
        Options Greeks
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {figures.map((f) => (
          <div key={f.label} className="rounded-md border border-border-muted px-3 py-2.5">
            <dt className="text-2xs text-text-tertiary">
              {f.label} · {f.hint}
            </dt>
            <dd className="mt-1 font-mono text-sm tabular-nums" data-financial>
              {f.value}
            </dd>
          </div>
        ))}
      </dl>
      {book.underlyings.length > 0 ? (
        <table className="mt-3 w-full text-xs" aria-label="Greeks by underlying">
          <thead>
            <tr className="text-left text-text-tertiary">
              <th className="font-normal">Underlying</th>
              <th className="text-right font-normal">Delta (shares)</th>
              <th className="text-right font-normal">Dollar delta</th>
              <th className="text-right font-normal">Gamma (shares per $1)</th>
              <th className="text-right font-normal">Theta/day</th>
            </tr>
          </thead>
          <tbody>
            {book.underlyings.map((u) => (
              <tr key={u.ticker}>
                <td className="ticker font-semibold">{u.ticker}</td>
                <td className="text-right font-mono" data-financial>
                  {u.delta_shares.toFixed(1)}
                </td>
                <td className="text-right font-mono" data-financial>
                  {signedUsd(u.dollar_delta)}
                </td>
                <td className="text-right font-mono" data-financial>
                  {u.gamma_shares.toFixed(2)}
                </td>
                <td className="text-right font-mono" data-financial>
                  {signedUsd(u.theta_per_day)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="mt-2 text-2xs text-text-tertiary">{book.method}.</p>
    </section>
  );
}

export function ExpirationView({ book }: { book: OptionsBook | null }) {
  if (!book || book.expirations.length === 0) return null;
  return (
    <section aria-labelledby="expirations-heading" className="mb-8">
      <h2 id="expirations-heading" className="text-lg font-semibold tracking-tight">
        Expirations
      </h2>
      <p className="mt-1 text-xs text-muted-foreground">
        What each expiry would do if the stock closed at today&apos;s price that day.
      </p>
      <ol className="mt-3 space-y-4">
        {book.expirations.map((group) => (
          <li key={group.expiry}>
            <h3 className="text-sm font-medium">{group.expiry}</h3>
            <ul className="mt-2 divide-y divide-border-muted border-y border-border-muted">
              {group.items.map((item) => (
                <li
                  key={`${item.strategy_id ?? item.label}`}
                  className="grid gap-1 py-2.5 text-xs sm:grid-cols-[minmax(0,1fr)_auto]"
                >
                  <div>
                    <p className="font-medium">{item.label}</p>
                    {item.legs.length > 1 ? (
                      <p className="text-text-tertiary">{item.legs.join(" · ")}</p>
                    ) : null}
                    <p className="mt-1 text-text-secondary">{item.outcome}</p>
                  </div>
                  <p className="text-right font-mono text-text-tertiary" data-financial>
                    {item.at_risk === null ? "Shares at risk" : `At risk ${usd(item.at_risk)}`}
                  </p>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}
