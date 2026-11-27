/**
 * A6.11 (M10.5): baskets the user takes to their broker. StockViz never places
 * an order: a basket from a trade plan, the rebalance preview or a screen
 * downloads as CSV or JSON (symbol, exchange, side, quantity, order type,
 * price, trigger) for the user to enter at their broker.
 *
 * With `KITE_API_KEY` set on the server (`GET /v1/broker/basket`), Indian
 * baskets can also go to Kite's offsite basket: a form in the user's browser
 * POSTs `api_key` and `data` (a JSON list) to
 * `https://kite.zerodha.com/connect/basket`, and the user reviews and confirms
 * the orders inside Zerodha (Kite Connect v3, "Offsite order execution", read
 * 26 Nov 2026). Kite's documented form carries the app's public `api_key`, so
 * the page holds it; the app secret never leaves the server.
 *
 * Client-safe and pure, so each builder is tested directly.
 */

export type BasketSide = "BUY" | "SELL";
export type BasketOrderType = "MARKET" | "LIMIT" | "SL" | "SL-M";

export type BasketOrder = {
  symbol: string;
  exchange: string;
  side: BasketSide;
  quantity: number;
  order_type: BasketOrderType;
  price: number | null;
  trigger: number | null;
  /** What the order is for ("Entry", "Stop", "Target", "Rebalance", "Screen"). */
  role: string;
};

export const KITE_BASKET_URL = "https://kite.zerodha.com/connect/basket";

/** Kite's basket form, for a client component: null while `KITE_API_KEY` is unset. */
export type KiteHandoff = { apiKey: string; url: string } | null;

/** `TCS.NS` -> TCS on NSE, `INFY.BO` -> INFY on BSE, anything else is a US symbol. */
export function brokerSymbol(ticker: string): { symbol: string; exchange: string } {
  const t = ticker.trim().toUpperCase();
  if (t.endsWith(".NS")) return { symbol: t.slice(0, -3), exchange: "NSE" };
  if (t.endsWith(".BO")) return { symbol: t.slice(0, -3), exchange: "BSE" };
  return { symbol: t, exchange: "US" };
}

function positiveNumber(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export type PlanLike = {
  ticker: string | null;
  status?: string;
  planned_entry: string | null;
  planned_stop: string | null;
  planned_target: string | null;
  planned_size: string | null;
};

/**
 * A plan's orders: the entry (a limit buy at the planned entry, or a market
 * buy without one), then its exits for the same size, a stop-loss sell
 * triggered at the stop and a limit sell at the target, each only when the
 * plan sets it. No size, no basket: a plan without one has no orders.
 */
export function basketFromPlan(plan: PlanLike): BasketOrder[] {
  const size = positiveNumber(plan.planned_size);
  if (!plan.ticker || size == null) return [];
  const quantity = Math.floor(size);
  if (quantity <= 0) return [];
  const { symbol, exchange } = brokerSymbol(plan.ticker);
  const entry = positiveNumber(plan.planned_entry);
  const stop = positiveNumber(plan.planned_stop);
  const target = positiveNumber(plan.planned_target);
  const out: BasketOrder[] = [
    {
      symbol,
      exchange,
      side: "BUY",
      quantity,
      order_type: entry == null ? "MARKET" : "LIMIT",
      price: entry,
      trigger: null,
      role: "Entry",
    },
  ];
  if (stop != null) {
    out.push({
      symbol,
      exchange,
      side: "SELL",
      quantity,
      order_type: "SL-M",
      price: null,
      trigger: stop,
      role: "Stop",
    });
  }
  if (target != null) {
    out.push({
      symbol,
      exchange,
      side: "SELL",
      quantity,
      order_type: "LIMIT",
      price: target,
      trigger: null,
      role: "Target",
    });
  }
  return out;
}

/** The rebalance preview's whole-share lines as market orders, sells first (they free cash). */
export function basketFromRebalance(
  lines: { ticker: string; side: "buy" | "sell"; quantity: number }[],
): BasketOrder[] {
  return [...lines]
    .filter((l) => l.quantity > 0)
    .sort((a, b) => (a.side === b.side ? 0 : a.side === "sell" ? -1 : 1))
    .map((l) => ({
      ...brokerSymbol(l.ticker),
      side: l.side === "buy" ? "BUY" : "SELL",
      quantity: Math.floor(l.quantity),
      order_type: "MARKET",
      price: null,
      trigger: null,
      role: "Rebalance",
    }));
}

/** A screen's rows as market buys of `quantity` shares each (the user sets it). */
export function basketFromScreen(tickers: string[], quantity: number): BasketOrder[] {
  const q = Math.floor(quantity);
  if (!(q > 0)) return [];
  return [...new Set(tickers)].map((ticker) => ({
    ...brokerSymbol(ticker),
    side: "BUY",
    quantity: q,
    order_type: "MARKET",
    price: null,
    trigger: null,
    role: "Screen",
  }));
}

const CSV_HEADER = ["symbol", "exchange", "side", "quantity", "order_type", "price", "trigger"];

function csvCell(value: string | number | null): string {
  if (value == null) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function basketCsv(orders: BasketOrder[]): string {
  const rows = orders.map((o) =>
    [o.symbol, o.exchange, o.side, o.quantity, o.order_type, o.price, o.trigger]
      .map(csvCell)
      .join(","),
  );
  return `${[CSV_HEADER.join(","), ...rows].join("\n")}\n`;
}

export function basketJson(orders: BasketOrder[]): string {
  return `${JSON.stringify(
    orders.map(({ symbol, exchange, side, quantity, order_type, price, trigger }) => ({
      symbol,
      exchange,
      side,
      quantity,
      order_type,
      price,
      trigger,
    })),
    null,
    2,
  )}\n`;
}

/** Kite's offsite basket takes NSE and BSE orders only. */
export function kiteEligible(orders: BasketOrder[]): BasketOrder[] {
  return orders.filter((o) => o.exchange === "NSE" || o.exchange === "BSE");
}

/**
 * The `data` field of Kite's basket form: one item per order, delivery
 * (`CNC`) and `regular`, in Kite's key names. A plan's basket sends only its
 * entry: the stop and target are exits, placed once the entry has filled.
 */
export function kiteBasketData(orders: BasketOrder[]): string {
  const items = kiteEligible(orders)
    .filter((o) => o.role !== "Stop" && o.role !== "Target")
    .map((o) => {
      const item: Record<string, string | number> = {
        variety: "regular",
        tradingsymbol: o.symbol,
        exchange: o.exchange,
        transaction_type: o.side,
        order_type: o.order_type,
        quantity: o.quantity,
        product: "CNC",
      };
      if (o.price != null) item.price = o.price;
      if (o.trigger != null) item.trigger_price = o.trigger;
      return item;
    });
  return JSON.stringify(items);
}

export function basketFileName(source: string, extension: "csv" | "json", day = new Date()) {
  const stamp = day.toISOString().slice(0, 10);
  const slug =
    source
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "basket";
  return `stockviz-basket-${slug}-${stamp}.${extension}`;
}
