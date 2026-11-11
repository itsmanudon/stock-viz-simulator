import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  openOptionAction: vi.fn(),
}));

const { OptionTradeForm } = await import("@/components/option-trade-form");

describe("option ticket client key (audit LG-10)", () => {
  it("posts a key the API accepts once the form is in the browser", () => {
    const { container } = render(<OptionTradeForm options={[{ ticker: "AAPL", name: "Apple" }]} />);

    const key = container.querySelector<HTMLInputElement>('input[name="client_order_id"]');
    expect(key?.value).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });
});
