/** A6.11 (M10.5): the basket builders and exports (lib/basket.ts), pure. */

import { describe, expect, it } from "vitest";

import {
  KITE_BASKET_URL,
  basketCsv,
  basketFileName,
  basketFromPlan,
  basketFromRebalance,
  basketFromScreen,
  basketJson,
  brokerSymbol,
  kiteBasketData,
} from "@/lib/basket";

const PLAN = {
  ticker: "TCS.NS",
  status: "open",
  planned_entry: "3500.50",
  planned_stop: "3400",
  planned_target: "3800",
  planned_size: "10",
};

describe("brokerSymbol", () => {
  it("splits the StockViz suffix into the broker's exchange", () => {
    expect(brokerSymbol("TCS.NS")).toEqual({ symbol: "TCS", exchange: "NSE" });
    expect(brokerSymbol("infy.bo")).toEqual({ symbol: "INFY", exchange: "BSE" });
    expect(brokerSymbol("AAPL")).toEqual({ symbol: "AAPL", exchange: "US" });
  });
});

describe("basketFromPlan", () => {
  it("holds exactly the plan's orders: entry, stop and target at the planned size", () => {
    expect(basketFromPlan(PLAN)).toEqual([
      {
        symbol: "TCS",
        exchange: "NSE",
        side: "BUY",
        quantity: 10,
        order_type: "LIMIT",
        price: 3500.5,
        trigger: null,
        role: "Entry",
      },
      {
        symbol: "TCS",
        exchange: "NSE",
        side: "SELL",
        quantity: 10,
        order_type: "SL-M",
        price: null,
        trigger: 3400,
        role: "Stop",
      },
      {
        symbol: "TCS",
        exchange: "NSE",
        side: "SELL",
        quantity: 10,
        order_type: "LIMIT",
        price: 3800,
        trigger: null,
        role: "Target",
      },
    ]);
  });

  it("leaves out the levels a plan does not set, and needs a size", () => {
    const entryOnly = basketFromPlan({ ...PLAN, planned_stop: null, planned_target: null });
    expect(entryOnly.map((o) => o.role)).toEqual(["Entry"]);
    const market = basketFromPlan({ ...PLAN, planned_entry: null, planned_target: null });
    expect(market.map((o) => [o.role, o.order_type])).toEqual([
      ["Entry", "MARKET"],
      ["Stop", "SL-M"],
    ]);
    expect(basketFromPlan({ ...PLAN, planned_size: null })).toEqual([]);
    expect(basketFromPlan({ ...PLAN, ticker: null })).toEqual([]);
  });
});

describe("basketFromRebalance and basketFromScreen", () => {
  it("turns rebalance lines into market orders, sells first", () => {
    const out = basketFromRebalance([
      { ticker: "AAPL", side: "buy", quantity: 3 },
      { ticker: "TCS.NS", side: "sell", quantity: 2 },
    ]);
    expect(out.map((o) => [o.symbol, o.side, o.quantity, o.order_type])).toEqual([
      ["TCS", "SELL", 2, "MARKET"],
      ["AAPL", "BUY", 3, "MARKET"],
    ]);
  });

  it("buys the same whole number of each screened symbol, once each", () => {
    const out = basketFromScreen(["AAPL", "TCS.NS", "AAPL"], 2.7);
    expect(out.map((o) => [o.symbol, o.exchange, o.quantity])).toEqual([
      ["AAPL", "US", 2],
      ["TCS", "NSE", 2],
    ]);
    expect(basketFromScreen(["AAPL"], 0)).toEqual([]);
  });
});

describe("exports", () => {
  it("CSV carries the seven columns and nothing else", () => {
    const csv = basketCsv(basketFromPlan(PLAN));
    expect(csv.split("\n")).toEqual([
      "symbol,exchange,side,quantity,order_type,price,trigger",
      "TCS,NSE,BUY,10,LIMIT,3500.5,",
      "TCS,NSE,SELL,10,SL-M,,3400",
      "TCS,NSE,SELL,10,LIMIT,3800,",
      "",
    ]);
  });

  it("JSON carries the same orders", () => {
    const parsed = JSON.parse(basketJson(basketFromPlan(PLAN)));
    expect(parsed).toHaveLength(3);
    expect(Object.keys(parsed[0])).toEqual([
      "symbol",
      "exchange",
      "side",
      "quantity",
      "order_type",
      "price",
      "trigger",
    ]);
  });

  it("names the file after its source and day", () => {
    expect(basketFileName("Plan TCS.NS", "csv", new Date("2026-11-26T10:00:00Z"))).toBe(
      "stockviz-basket-plan-tcs-ns-2026-11-26.csv",
    );
  });
});

describe("kiteBasketData", () => {
  it("is Kite's documented item shape, entry only for a plan, Indian orders only", () => {
    const items = JSON.parse(kiteBasketData(basketFromPlan(PLAN)));
    expect(items).toEqual([
      {
        variety: "regular",
        tradingsymbol: "TCS",
        exchange: "NSE",
        transaction_type: "BUY",
        order_type: "LIMIT",
        quantity: 10,
        product: "CNC",
        price: 3500.5,
      },
    ]);
    const mixed = JSON.parse(
      kiteBasketData(
        basketFromRebalance([
          { ticker: "AAPL", side: "buy", quantity: 1 },
          { ticker: "INFY.BO", side: "sell", quantity: 4 },
        ]),
      ),
    );
    expect(mixed.map((i: { tradingsymbol: string }) => i.tradingsymbol)).toEqual(["INFY"]);
    expect(KITE_BASKET_URL).toBe("https://kite.zerodha.com/connect/basket");
  });
});
