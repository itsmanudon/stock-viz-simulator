import Link from "next/link";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Position } from "@/lib/api/trading";
import {
  calculatePortfolioWeight,
  formatCurrency,
  formatQuantity,
  formatSignedCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";

type Props = {
  positions: Position[];
  displayCurrency: string;
  totalValue: string;
};

export function PortfolioPositions({ positions, displayCurrency, totalValue }: Props) {
  if (positions.length === 0) {
    return <p className="text-sm text-muted-foreground">No stock positions are currently open.</p>;
  }

  return (
    <section aria-labelledby="positions-heading">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="positions-heading" className="text-lg font-semibold tracking-tight">
            Stock positions
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Values in {displayCurrency}; security prices remain in their native currency.
          </p>
        </div>
        <p className="text-xs text-muted-foreground">Latest available EOD closes</p>
      </div>

      <div className="hidden overflow-hidden border-y border-border-muted md:block">
        <Table aria-label="Stock positions">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Symbol / company</TableHead>
              <TableHead className="text-right">Quantity</TableHead>
              <TableHead className="text-right">Avg cost</TableHead>
              <TableHead className="text-right">Last EOD</TableHead>
              <TableHead className="text-right">Market value</TableHead>
              <TableHead className="text-right">Unrealized P&amp;L</TableHead>
              <TableHead className="text-right">Weight</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map((position) => (
              <DesktopPositionRow
                key={position.ticker}
                position={position}
                displayCurrency={displayCurrency}
                totalValue={totalValue}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <ul aria-label="Stock positions on mobile" className="divide-y divide-border-muted md:hidden">
        {positions.map((position) => (
          <MobilePositionRow
            key={position.ticker}
            position={position}
            displayCurrency={displayCurrency}
          />
        ))}
      </ul>
    </section>
  );
}

function DesktopPositionRow({
  position,
  displayCurrency,
  totalValue,
}: {
  position: Position;
  displayCurrency: string;
  totalValue: string;
}) {
  const values = positionValues(position);
  const weight = calculatePortfolioWeight(position.market_value, totalValue);
  const showNative = position.currency !== displayCurrency;

  return (
    <TableRow className="group border-border-muted hover:bg-surface-hover/70">
      <TableCell className="max-w-56">
        <Link
          href={`/stocks/${position.ticker}`}
          className="font-mono text-sm font-semibold outline-none hover:text-brand focus-visible:text-brand focus-visible:underline"
        >
          {position.ticker}
        </Link>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">{position.name}</p>
      </TableCell>
      <TableCell className="text-right font-mono" data-financial>
        {formatQuantity(position.quantity)}
        {Number(position.reserved_quantity) > 0 ? (
          <span className="mt-0.5 block text-[11px] text-muted-foreground">
            {formatQuantity(position.available_quantity)} available
          </span>
        ) : null}
      </TableCell>
      <TableCell className="text-right font-mono" data-financial>
        {formatCurrency(position.avg_cost, position.currency)}
      </TableCell>
      <TableCell className="text-right font-mono" data-financial>
        {formatCurrency(position.last_close, position.currency)}
      </TableCell>
      <TableCell className="text-right font-mono font-medium" data-financial>
        {formatCurrency(position.market_value, displayCurrency)}
        {showNative ? (
          <span className="mt-0.5 block text-[11px] font-normal text-muted-foreground">
            {formatCurrency(position.market_value_native, position.currency)} native
          </span>
        ) : null}
      </TableCell>
      <TableCell className={`text-right font-mono ${values.tone}`} data-financial>
        <span className="block text-sm font-medium">
          {values.direction} {formatSignedCurrency(position.unrealized_pl, displayCurrency)}
        </span>
        <span className="mt-0.5 block text-[11px]">{formatSignedPercent(values.returnPct)}</span>
      </TableCell>
      <TableCell className="text-right font-mono text-sm" data-financial>
        {weight === null ? "—" : `${weight.toFixed(2)}%`}
      </TableCell>
      <TableCell className="text-right">
        <Link
          href={`/trade?ticker=${encodeURIComponent(position.ticker)}`}
          aria-label={`Trade ${position.ticker}`}
          className="text-xs font-medium text-muted-foreground outline-none transition-colors hover:text-brand focus-visible:text-brand focus-visible:underline"
        >
          Trade
        </Link>
      </TableCell>
    </TableRow>
  );
}

function MobilePositionRow({
  position,
  displayCurrency,
}: {
  position: Position;
  displayCurrency: string;
}) {
  const values = positionValues(position);
  const availability =
    Number(position.reserved_quantity) > 0
      ? ` · ${formatQuantity(position.available_quantity)} available`
      : "";

  return (
    <li
      aria-label={`${position.ticker} ${position.name}`}
      className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-3 py-5"
    >
      <div className="min-w-0">
        <Link
          href={`/stocks/${position.ticker}`}
          className="font-mono font-semibold hover:text-brand"
        >
          {position.ticker}
        </Link>
        <p className="truncate text-xs text-muted-foreground">{position.name}</p>
      </div>
      <div className="text-right">
        <p className="text-[11px] text-muted-foreground">Market value</p>
        <p className="font-mono font-semibold" data-financial>
          {formatCurrency(position.market_value, displayCurrency)}
        </p>
      </div>
      <div>
        <p className="font-mono text-sm" data-financial>
          {formatQuantity(position.quantity)} shares{availability}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Avg {formatCurrency(position.avg_cost, position.currency)} · Last EOD{" "}
          {formatCurrency(position.last_close, position.currency)}
        </p>
      </div>
      <div className={`text-right font-mono ${values.tone}`} data-financial>
        <p className="text-sm font-medium">
          {values.direction} {formatSignedCurrency(position.unrealized_pl, displayCurrency)}
        </p>
        <p className="mt-1 text-xs">{formatSignedPercent(values.returnPct)}</p>
      </div>
    </li>
  );
}

function positionValues(position: Position) {
  const marketValue = Number(position.market_value);
  const pnl = Number(position.unrealized_pl);
  const displayCost = marketValue - pnl;
  const returnPct =
    Number.isFinite(pnl) && Number.isFinite(displayCost) && displayCost !== 0
      ? (pnl / displayCost) * 100
      : null;

  return {
    returnPct,
    direction: pnl > 0 ? "Gain" : pnl < 0 ? "Loss" : "Flat",
    tone: pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-foreground",
  };
}
