import { describe, expect, it } from "vitest";

import {
  buildAlertsHref,
  buildOrdersHref,
  buildTradeHref,
  parseAlertView,
  parseOrdersStatus,
  parseTradeTicker,
  userCancelReason,
} from "@/lib/operational-trading";

describe("trade ticker query", () => {
  it("normalizes and rejects empty or oversized tickers", () => {
    expect(parseTradeTicker("aapl")).toBe("AAPL");
    expect(parseTradeTicker("  msft ")).toBe("MSFT");
    expect(parseTradeTicker("")).toBe("");
    expect(parseTradeTicker("THIS-IS-WAY-TOO-LONG")).toBe("");
    expect(buildTradeHref("AAPL")).toBe("/trade?ticker=AAPL");
    expect(buildTradeHref()).toBe("/trade");
  });
});

describe("orders status query", () => {
  it("defaults to pending and preserves supported filters", () => {
    expect(parseOrdersStatus(undefined)).toBe("pending");
    expect(parseOrdersStatus("filled")).toBe("filled");
    expect(parseOrdersStatus("nope")).toBe("pending");
    expect(buildOrdersHref("pending")).toBe("/orders");
    expect(buildOrdersHref("cancelled")).toBe("/orders?status=cancelled");
  });
});

describe("alerts query", () => {
  it("builds view and ticker deep links", () => {
    expect(parseAlertView(undefined)).toBe("active");
    expect(parseAlertView("triggered")).toBe("triggered");
    expect(buildAlertsHref()).toBe("/alerts");
    expect(buildAlertsHref({ view: "triggered", ticker: "AAPL" })).toBe(
      "/alerts?view=triggered&ticker=AAPL",
    );
  });
});

describe("userCancelReason", () => {
  it("surfaces API reasons and labels empty user cancels", () => {
    expect(userCancelReason("Insufficient cash")).toBe("Insufficient cash");
    expect(userCancelReason(null)).toBe("Cancelled by user");
    expect(userCancelReason("  ")).toBe("Cancelled by user");
  });
});
