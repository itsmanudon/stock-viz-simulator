import Link from "next/link";

import { closeOptionAction } from "@/app/(product)/(authed)/trade/options-actions";
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
          Modelled values in {displayCurrency}; no realtime option quote or Greeks implied.
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
              <TableHead className="text-right">Premium paid · USD</TableHead>
              <TableHead className="text-right">Estimated value</TableHead>
              <TableHead className="text-right">Unrealized P&amp;L</TableHead>
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
                      className="font-mono font-semibold hover:text-brand focus-visible:text-brand focus-visible:underline"
                    >
                      {position.ticker}
                    </Link>
                    <span className="ml-2 text-xs font-medium capitalize text-muted-foreground">
                      {position.option_type}
                    </span>
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
                  <TableCell className="text-right">
                    <CloseOptionButton position={position} />
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
                <Link href={`/stocks/${position.ticker}`} className="font-mono font-semibold">
                  {position.ticker}
                </Link>
                <p className="mt-1 text-xs capitalize text-muted-foreground">
                  {position.option_type} · {formatCurrency(position.strike, position.currency)} ·{" "}
                  {formatDate(position.expiry)}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatQuantity(position.quantity)} contracts · Premium{" "}
                  {formatCurrency(position.premium_paid, "USD")} USD
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
                  <CloseOptionButton position={position} />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function CloseOptionButton({ position }: { position: PortfolioOption }) {
  return (
    <form action={closeOptionAction}>
      <input type="hidden" name="option_id" value={position.option_id} />
      <button
        type="submit"
        aria-label={`Close ${position.ticker} ${position.option_type} position`}
        className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        Close
      </button>
    </form>
  );
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
