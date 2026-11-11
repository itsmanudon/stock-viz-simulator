import { beforeEach, describe, expect, it, vi } from "vitest";

const postTrade = vi.fn();
const createOrder = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/lib/api/server", () => ({
  AuthedApiError: class extends Error {},
  UnauthenticatedError: class extends Error {},
}));
vi.mock("@/lib/api/trading", () => ({
  postTrade: (...args: unknown[]) => postTrade(...args),
  createOrder: (...args: unknown[]) => createOrder(...args),
}));

import { REVIEW_REQUIRED_ERROR, newClientOrderId } from "@/lib/order-review";

const { placeOrderAction, placeTradeAction } = await import(
  "@/app/(product)/(authed)/trade/actions"
);

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
}

const trade = { ticker: "AAPL", side: "buy", quantity: "1" };

describe("trade actions review guard", () => {
  beforeEach(() => {
    postTrade.mockReset().mockResolvedValue({
      ticker: "AAPL",
      side: "buy",
      quantity: "1",
      price: "25",
      currency: "USD",
      total_native: "25",
      total_usd: "25",
    });
    createOrder.mockReset().mockResolvedValue({
      order_type: "limit",
      side: "buy",
      quantity: "1",
      ticker: "AAPL",
      limit_price: "20",
    });
  });

  it("refuses a market order posted before the review was opened", async () => {
    const result = await placeTradeAction({}, form({ ...trade, review_step: "draft" }));

    expect(result).toEqual({ error: REVIEW_REQUIRED_ERROR });
    expect(postTrade).not.toHaveBeenCalled();
  });

  it("refuses a pending order posted before the review was opened", async () => {
    const result = await placeOrderAction(
      {},
      form({ ...trade, order_type: "limit", limit_price: "20", review_step: "draft" }),
    );

    expect(result).toEqual({ error: REVIEW_REQUIRED_ERROR });
    expect(createOrder).not.toHaveBeenCalled();
  });

  it("places the order once the review confirmed it", async () => {
    const result = await placeTradeAction({}, form({ ...trade, review_step: "confirmed" }));

    expect(result.success?.ticker).toBe("AAPL");
    expect(postTrade).toHaveBeenCalledTimes(1);
  });

  it("leaves tickets without a review step unchanged", async () => {
    await placeTradeAction({}, form(trade));

    expect(postTrade).toHaveBeenCalledTimes(1);
  });
});

describe("client order keys (#67)", () => {
  beforeEach(() => {
    postTrade.mockReset().mockResolvedValue({
      ticker: "AAPL",
      side: "buy",
      quantity: "1",
      price: "25",
      currency: "USD",
      total_native: "25",
      total_usd: "25",
    });
    createOrder.mockReset().mockResolvedValue({
      order_type: "limit",
      side: "buy",
      quantity: "1",
      ticker: "AAPL",
      limit_price: "20",
    });
  });

  it("passes the review's key to the API for market and pending orders", async () => {
    await placeTradeAction({}, form({ ...trade, client_order_id: "key-1" }));
    await placeOrderAction(
      {},
      form({ ...trade, order_type: "limit", limit_price: "20", client_order_id: "key-2" }),
    );

    expect(postTrade.mock.calls[0]?.[0]).toMatchObject({ client_order_id: "key-1" });
    expect(createOrder.mock.calls[0]?.[0]).toMatchObject({ client_order_id: "key-2" });
  });

  it("drops a key the API would refuse rather than failing the order", async () => {
    await placeTradeAction({}, form({ ...trade, client_order_id: "has spaces" }));

    expect(postTrade.mock.calls[0]?.[0]).toMatchObject({ client_order_id: undefined });
  });

  it("makes keys the API accepts, different every time", () => {
    const keys = new Set(Array.from({ length: 20 }, () => newClientOrderId()));

    expect(keys.size).toBe(20);
    for (const key of keys) expect(key).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });
});
