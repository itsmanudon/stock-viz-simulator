"use client";

import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ReplayFill } from "@/lib/api/replay";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { formatReplayShortDate } from "@/lib/replay";

export function ReplayFillTable({ fills }: { fills: ReplayFill[] }) {
  if (fills.length === 0) {
    return (
      <ResearchEmptyState title="No replay trades yet.">
        Submit a market order against this session&apos;s stored close. Nothing is sent to your live
        paper book.
      </ResearchEmptyState>
    );
  }

  return (
    <section aria-labelledby="replay-fills-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-fills-heading"
        title="Replay fills"
        description="Chronological fills on this isolated book. Expand a row for execution provenance."
      />
      <div className="border-y border-border-muted sm:border-x">
        <Table aria-label="Replay fills">
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Fill</TableHead>
              <TableHead className="text-right">Realized P&amp;L</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Profile</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fills.map((fill) => (
              <ReplayFillRows key={fill.id} fill={fill} />
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function ReplayFillRows({ fill }: { fill: ReplayFill }) {
  return (
    <>
      <TableRow>
        <TableCell>{formatReplayShortDate(fill.evaluated_at)}</TableCell>
        <TableCell>{fill.ticker}</TableCell>
        <TableCell className="uppercase">{fill.side}</TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {formatQuantity(fill.quantity)}
        </TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {formatCurrency(fill.fill_price)}
        </TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {fill.realized_pnl === null ? "—" : formatCurrency(fill.realized_pnl)}
        </TableCell>
        <TableCell className="uppercase">{fill.order_type.replaceAll("_", " ")}</TableCell>
        <TableCell>
          {fill.profile_name} {fill.model_version}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={8} className="bg-surface-elevated/40">
          <details>
            <summary className="cursor-pointer text-xs font-medium text-text-secondary">
              Why this filled
            </summary>
            <dl className="mt-2 grid gap-1 text-xs text-text-tertiary sm:grid-cols-2">
              <div>
                Reference price: {fill.reference_price ? formatCurrency(fill.reference_price) : "—"}
              </div>
              <div>Fill price: {formatCurrency(fill.fill_price)}</div>
              <div>
                Profile: {fill.profile_name} {fill.model_version}
              </div>
              <div>Interval: {fill.market_interval}</div>
              <div>Evaluated: {formatReplayShortDate(fill.evaluated_at)}</div>
              <div>Reason: {fill.reason}</div>
            </dl>
            {fill.assumptions.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-text-tertiary">
                {fill.assumptions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </details>
        </TableCell>
      </TableRow>
    </>
  );
}
