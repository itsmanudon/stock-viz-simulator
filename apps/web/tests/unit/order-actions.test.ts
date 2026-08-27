import { beforeEach, describe, expect, it, vi } from "vitest";

import { cancelOrderAction } from "@/app/(product)/(authed)/orders/actions";
import { cancelOrder } from "@/lib/api/trading";
import { revalidatePath } from "next/cache";

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

vi.mock("@/lib/api/trading", () => ({
  cancelOrder: vi.fn(),
}));

vi.mock("@/lib/api/server", () => ({
  AuthedApiError: class AuthedApiError extends Error {
    status: number;

    constructor(status: number) {
      super(`API error ${status}`);
      this.status = status;
    }
  },
  UnauthenticatedError: class UnauthenticatedError extends Error {},
}));

describe("order actions", () => {
  beforeEach(() => {
    vi.mocked(cancelOrder).mockReset();
    vi.mocked(revalidatePath).mockReset();
  });

  it("refreshes standalone, stock, and portfolio order contexts after cancellation", async () => {
    const formData = new FormData();
    formData.set("id", "42");
    formData.set("ticker", "aapl");

    await cancelOrderAction(formData);

    expect(cancelOrder).toHaveBeenCalledWith(42);
    expect(revalidatePath).toHaveBeenCalledWith("/orders");
    expect(revalidatePath).toHaveBeenCalledWith("/stocks/AAPL");
    expect(revalidatePath).toHaveBeenCalledWith("/portfolio");
  });
});
