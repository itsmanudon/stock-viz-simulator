/**
 * A5.2: every trade ticket says which book it fills in, and why it can't when
 * the selection takes no trades (All books, an archived or imported book).
 */

/** The book a ticket trades into (A5.2). */
export type TicketBook = { id: number; name: string; currency: string };

/** "Trades into Growth (INR)": every ticket says which book it fills in. */
export function TicketBookLine({
  book,
  blockedReason,
}: {
  book: TicketBook | null | undefined;
  blockedReason: string | null | undefined;
}) {
  return (
    <div className="mt-2 space-y-2">
      {book && !blockedReason ? (
        <p className="text-xs text-text-secondary" data-testid="ticket-book">
          Trades into <span className="font-medium text-foreground">{book.name}</span>{" "}
          <span className="font-mono text-text-tertiary">({book.currency})</span>
        </p>
      ) : null}
      {blockedReason ? (
        <p
          role="note"
          data-testid="ticket-blocked"
          className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-xs text-warning-soft-foreground"
        >
          {blockedReason}
        </p>
      ) : null}
    </div>
  );
}
