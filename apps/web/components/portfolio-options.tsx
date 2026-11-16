import Link from "next/link";

import { CloseOptionButton } from "@/components/close-option-button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PortfolioOption } from "@/lib/api/trading";
import { formatCurrency, formatQuantity, formatSignedCurrency } from "@/lib/portfolio-view-model";

export function PortfolioOptions({
  positions,
  displayCurrency,
}: {
  positions: PortfolioOption[];
  displayCurrency: string;
}) {
  if (positions.length === 0) {
    return (
      <PanelState
        title="No option positions are currently open."
        description="Options exposure will appear here after a paper options trade."
      />
    );
  }

  return (
    <section aria-labelledby="options-positions-heading">
      <div className="mb-4">
        <h2 id="options-positions-heading" className="text-lg font-semibold tracking-tight">
          Options exposure
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Modelled values in {displayCurrency}: Black-Scholes on a stored option chain&apos;s
          implied volatility, or 30-day historical volatility, not market quotes. Greeks are per
          share; theta is per day.
        </p>
      </div>

      <div className="hidden overflow-hidden border-y border-border-muted md:block">
        <Table aria-label="Options positions">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Contract</TableHead>
              <TableHead className="text-right">Strike</TableHead>
              <TableHead>Expiry</TableHead>
              <TableHead className="text-right">Contracts</TableHead>
              <TableHead className="text-right">Premium · USD</TableHead>
              <TableHead className="text-right">Estimated value</TableHead>
              <TableHead className="text-right">Unrealized P&amp;L</TableHead>
              <TableHead className="text-right">Delta · Theta/day</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map((position) => {
              const pnl = Number(position.unrealized_pl);
              const tone = pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "";
              const direction = pnl > 0 ? "Gain" : pnl < 0 ? "Loss" : "Flat";
              return (
                <TableRow key={position.option_id} className="border-border-muted">
                  <TableCell>
                    <Link
                      href={`/stocks/${position.ticker}`}
                      className="ticker font-semibold hover:text-brand focus-visible:text-brand focus-visible:underline"
                    >
                      {position.ticker}
                    </Link>
                    <span className="ml-2 text-xs font-medium text-muted-foreground">
                      {contractLabel(position)}
                    </span>
                    {position.strategy ? (
                      <span className="mt-0.5 block text-2xs text-muted-foreground">
                        Leg of a {position.strategy.toLowerCase()}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right font-mono" data-financial>
                    {formatCurrency(position.strike, position.currency)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(position.expiry)}
                  </TableCell>
                  <TableCell className="text-right font-mono" data-financial>
                    {formatQuantity(position.quantity)}
                  </TableCell>
                  <TableCell className="text-right font-mono" data-financial>
                    {formatCurrency(position.premium_paid, "USD")}
                    <span className="mt-0.5 block text-2xs text-muted-foreground">
                      {position.side === "short" ? "received" : "paid"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono" data-financial>
                    {formatCurrency(position.market_value, displayCurrency)}
                    {position.currency !== displayCurrency ? (
                      <span className="mt-0.5 block text-2xs text-muted-foreground">
                        {formatCurrency(position.market_value_native, position.currency)} native
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className={`text-right font-mono ${tone}`} data-financial>
                    {direction} {formatSignedCurrency(position.unrealized_pl, displayCurrency)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs" data-financial>
                    <GreeksCell position={position} />
                  </TableCell>
                  <TableCell className="text-right">
                    <CloseOption position={position} displayCurrency={displayCurrency} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <ul
        aria-label="Options positions on mobile"
        className="divide-y divide-border-muted md:hidden"
      >
        {positions.map((position) => {
          const pnl = Number(position.unrealized_pl);
          return (
            <li
              key={position.option_id}
              aria-label={`${position.ticker} ${position.option_type} option`}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-5"
            >
              <div>
                <Link href={`/stocks/${position.ticker}`} className="ticker font-semibold">
                  {position.ticker}
                </Link>
                <p className="mt-1 text-xs text-muted-foreground">
                  {contractLabel(position)} · {formatCurrency(position.strike, position.currency)} ·{" "}
                  {formatDate(position.expiry)}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatQuantity(position.quantity)} contracts · Premium{" "}
                  {position.side === "short" ? "received" : "paid"}{" "}
                  {formatCurrency(position.premium_paid, "USD")} USD
                </p>
                <p className="mt-1 font-mono text-xs text-muted-foreground" data-financial>
                  <GreeksCell position={position} />
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono font-semibold" data-financial>
                  {formatCurrency(position.market_value, displayCurrency)}
                </p>
                <p
                  className={`mt-1 font-mono text-xs ${
                    pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : ""
                  }`}
                  data-financial
                >
                  {pnl > 0 ? "Gain " : pnl < 0 ? "Loss " : "Flat "}
                  {formatSignedCurrency(position.unrealized_pl, displayCurrency)}
                </p>
                <div className="mt-3">
                  <CloseOption position={position} displayCurrency={displayCurrency} />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Per-share delta and theta, or a dash when the contract cannot be priced. */
function GreeksCell({ position }: { position: PortfolioOption }) {
  const greeks = position.greeks;
  if (!greeks) return <span aria-label="Greeks unavailable">-</span>;
  return (
    <span aria-label={`Delta ${greeks.delta.toFixed(2)}, theta ${greeks.theta.toFixed(2)} a day`}>
      Δ {greeks.delta.toFixed(2)} · Θ {formatCurrency(String(greeks.theta), position.currency)}
    </span>
  );
}

function CloseOption({
  position,
  displayCurrency,
}: {
  position: PortfolioOption;
  displayCurrency: string;
}) {
  // Past expiry the API refuses a close until the nightly settlement (LG-8).
  if (position.expiry < newYorkToday()) {
    return <span className="text-2xs text-muted-foreground">Awaiting settlement</span>;
  }
  return (
    <CloseOptionButton
      optionId={position.option_id}
      label={`${position.ticker} ${position.side === "short" ? "written " : ""}${position.option_type} position`}
      valueText={formatCurrency(String(Math.abs(Number(position.market_value))), displayCurrency)}
      short={position.side === "short"}
    />
  );
}

/** "call" or "put"; a written leg says what covers it (Phase 9.2). */
function contractLabel(position: PortfolioOption): string {
  if (position.side !== "short") return position.option_type;
  // A short leg of a spread or calendar is covered by the strategy's long leg.
  const coveredBySpread =
    position.strategy && !["Covered call", "Cash-secured put"].includes(position.strategy);
  if (coveredBySpread) return `${position.option_type} (written)`;
  return position.option_type === "call" ? "Covered call (written)" : "Cash-secured put (written)";
}

/** Today's date in New York, as YYYY-MM-DD, the date the API compares expiry with. */
function newYorkToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

function PanelState({ title, description }: { title: string; description: string }) {
  return (
    <div className="border-y border-border-muted py-8 text-sm">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-muted-foreground">{description}</p>
    </div>
  );
}

function formatDate(raw: string) {
  return new Date(`${raw}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
