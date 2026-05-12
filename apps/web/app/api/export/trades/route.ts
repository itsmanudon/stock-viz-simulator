import { UnauthenticatedError } from "@/lib/api/server";
import { listTrades } from "@/lib/api/trading";

export async function GET() {
  try {
    const trades = await listTrades(500);

    const lines = [
      "Time,Ticker,Side,Quantity,Price,Total",
      ...trades.map((t) => {
        const total = (Number(t.quantity) * Number(t.price)).toFixed(2);
        return `${new Date(t.ts).toISOString()},${t.ticker},${t.side},${t.quantity},${t.price},${total}`;
      }),
    ];

    return new Response(lines.join("\n"), {
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": 'attachment; filename="trades.csv"',
      },
    });
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      return new Response("Unauthorized", { status: 401 });
    }
    return new Response("Internal Server Error", { status: 500 });
  }
}
