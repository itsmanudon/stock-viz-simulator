"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { JournalExecution } from "@/lib/api/journal";
import { JOURNAL_TIMEZONE } from "@/lib/journal-view-model";
import { formatCurrency, formatQuantity } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";

/**
 * One closing execution in the day inspector.
 *
 * Equity and option legs share the frame but not the fields — an option has a
 * premium and a contract, not an entry price and a share count, and pretending
 * otherwise would misstate both.
 *
 * `Signal at entry` is reserved for persisted opening-decision provenance.
 * The current API returns null because closing fills lack opening links.
 */
export function JournalExecutionRow({ execution }: { execution: JournalExecution }) {
  const pnl = Number(execution.realized_pnl);
  const isOption = execution.kind === "option";

  return (
    <li className="border-b border-border-muted py-3.5 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/stocks/${execution.ticker}`}
            className="font-mono text-sm font-semibold hover:underline"
          >
            {execution.ticker}
          </Link>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {isOption ? describeOption(execution) : describeEquity(execution)}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <p
            data-financial
            className={cn(
              "font-mono text-sm font-semibold",
              pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-text-secondary",
            )}
          >
            {pnl > 0 ? "+" : pnl < 0 ? "−" : ""}
            {formatCurrency(Math.abs(pnl), "USD")}
          </p>
          <p className="font-mono text-3xs text-text-tertiary">
            {new Date(execution.executed_at).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: JOURNAL_TIMEZONE,
            })}
            {" ET"}
          </p>
        </div>
      </div>

      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        {isOption ? (
          <>
            <Field label="Premium paid" value={money(execution.premium_paid, execution.currency)} />
            <Field label="Proceeds" value={money(execution.proceeds, execution.currency)} />
            <Field label="Outcome" value={execution.option_status ?? "—"} />
          </>
        ) : (
          <>
            <Field label="Average cost" value={money(execution.avg_cost, execution.currency)} />
            <Field label="Exit" value={money(execution.price, execution.currency)} />
            <Field
              label="Quantity"
              value={execution.quantity === null ? "—" : formatQuantity(execution.quantity)}
            />
          </>
        )}
      </dl>

      {execution.signal_at_entry ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Signal at entry</span>
          <Badge variant="secondary" className="font-mono text-2xs">
            {execution.signal_at_entry.score} / {execution.signal_at_entry.max_score} votes
          </Badge>
          <Link
            href={`/recommendations?q=${execution.ticker}`}
            className="inline-flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Signals
            <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        </div>
      ) : null}
    </li>
  );
}

function describeEquity(execution: JournalExecution): string {
  const quantity = execution.quantity === null ? "—" : formatQuantity(execution.quantity);
  // A sell against a long position closes it; the ledger is long-only for
  // equities, so "Closed long" is accurate rather than inferred.
  return `Closed long · ${quantity} shares`;
}

function describeOption(execution: JournalExecution): string {
  const type = execution.option_type === "put" ? "PUT" : "CALL";
  const strike = execution.strike === null ? "" : ` ${Number(execution.strike).toFixed(2)}`;
  const expiry = execution.expiry ? ` exp ${execution.expiry}` : "";
  const contracts = execution.contracts ?? 0;
  return `LONG ${type}${strike}${expiry} · ${contracts} ${contracts === 1 ? "contract" : "contracts"}`;
}

function money(raw: string | null, currency: string): string {
  return raw === null ? "—" : formatCurrency(raw, currency);
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-3xs uppercase tracking-wide text-text-tertiary">{label}</dt>
      <dd data-financial className="truncate font-mono text-xs">
        {value}
      </dd>
    </div>
  );
}
