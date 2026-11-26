/**
 * Broker status in plain words (A5.7, M1.7), on Settings, `/status` and an
 * imported book. Never an error: a status that could not be read says so
 * and the page carries on. No live broker connection exists; see
 * `lib/broker-status.ts` for the copy.
 */

import { PlugZap } from "lucide-react";

import { StatusBadge } from "@/components/status-badge";
import { type BrokerStatusLike, brokerCopy, brokerLine } from "@/lib/broker-status";
import { cn } from "@/lib/utils";

export function BrokerStatusList({
  brokers,
  className,
}: {
  /** Null when the status could not be read. */
  brokers: BrokerStatusLike[] | null;
  className?: string;
}) {
  if (!brokers) {
    return (
      <p className={cn("text-sm text-text-secondary", className)} data-testid="broker-status">
        Broker status could not be read just now. Prices stay end of day, and imported books update
        when you upload a tradebook (CSV).
      </p>
    );
  }
  return (
    <ul className={cn("space-y-3", className)} data-testid="broker-status">
      {brokers.map((b) => {
        const copy = brokerCopy(b);
        return (
          <li key={b.label} className="text-sm" data-state={b.state}>
            <p className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-foreground">{copy.headline}</span>
              <StatusBadge label={copy.badge.label} tone={copy.badge.tone} />
            </p>
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">{copy.detail}</p>
            <p className="mt-1 text-xs leading-relaxed text-text-tertiary">{copy.imports}</p>
          </li>
        );
      })}
    </ul>
  );
}

/** One line under an imported book's notice or empty state. */
export function BrokerStatusLine({
  broker,
  className,
}: {
  broker: BrokerStatusLike | null;
  className?: string;
}) {
  return (
    <p
      className={cn("flex items-start gap-2 text-xs text-text-secondary", className)}
      data-testid="broker-status-line"
    >
      <PlugZap className="mt-px size-3.5 shrink-0 text-text-tertiary" aria-hidden />
      <span>{brokerLine(broker)}</span>
    </p>
  );
}
