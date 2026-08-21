/**
 * CSV export of the signed-in user's trade history.
 *
 * The totals column is explicitly currency-labelled: trade price and quantity
 * are in the symbol's native currency, while the USD total uses the FX rate
 * captured at fill time. The previous version emitted a single unlabelled
 * `Total` built from price x quantity, which is meaningless for a portfolio
 * holding non-USD symbols.
 */

import { UnauthenticatedError } from "@/lib/api/server";
import { listTrades } from "@/lib/api/trading";
import { toCsv } from "@/lib/csv";

const HEADER = [
  "Time",
  "Ticker",
  "Side",
  "Quantity",
  "Price (native)",
  "Currency",
  "FX rate (USD per unit)",
  "Total (native)",
  "Total (USD)",
  "Realized P&L (USD)",
];

export async function GET() {
  try {
    const trades = await listTrades(500);

    const rows = trades.map((t) => {
      const native = Number(t.quantity) * Number(t.price);
      const rate = Number(t.fx_rate);
      return [
        new Date(t.ts).toISOString(),
        t.ticker,
        t.side,
        t.quantity,
        t.price,
        t.currency,
        rate,
        native.toFixed(2),
        (native * rate).toFixed(2),
        t.realized_pnl === null || t.realized_pnl === undefined
          ? ""
          : Number(t.realized_pnl).toFixed(2),
      ];
    });

    const filename = `stockviz-trades-${new Date().toISOString().slice(0, 10)}.csv`;
    return new Response(toCsv(HEADER, rows), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return new Response("Unauthorized", { status: 401 });
    }
    return new Response("Internal Server Error", { status: 500 });
  }
}
