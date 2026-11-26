import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CostsDisclosure } from "@/components/costs-disclosure";
import { OrderReview } from "@/components/order-review";
import { advCapValue, feesSuffix, partialLabel, sourceDated, versionRange } from "@/lib/fees";
import type { CostsOut } from "@/lib/fees";

vi.mock("@/lib/api/fees", () => ({
  getFeeEstimate: vi.fn().mockResolvedValue({
    ticker: "TCS.NS",
    side: "buy",
    quantity: "10",
    price: "2500",
    currency: "INR",
    schedule: "in_equity_delivery_nse",
    label: "NSE equity delivery",
    on: "2026-11-26",
    effective_from: "2026-03-01",
    before_coverage: false,
    notional: "25000",
    total: "30.55",
    net_amount: "25030.55",
    lines: [
      {
        key: "stt",
        label: "Securities transaction tax (STT)",
        amount: "25",
        rate_text: "0.1% of value",
        source: {
          url: "https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf",
          title: "NSE/FATAX/73524",
          date: "2026-03-31",
          read_on: "2026-11-26",
        },
      },
      {
        key: "stamp_duty",
        label: "Stamp duty",
        amount: "3.75",
        rate_text: "0.015% of value",
        source: null,
      },
    ],
  }),
}));

const source = {
  url: "https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf",
  title: "NSE/FATAX/73524",
  date: "2026-03-31",
  read_on: "2026-11-26",
};

const costs: CostsOut = {
  schedule: "in_futures_nse",
  requested: "auto",
  label: "NSE equity futures",
  currency: "INR",
  segment: "futures",
  brokerage: { key: "zerodha", label: "Zerodha", rate_text: "0.03% or 20", source: null },
  commission_bps: 0,
  coverage_from: "2024-10-01",
  fills_before_coverage: 2,
  versions: [
    {
      effective_from: "2026-03-01",
      effective_to: "2026-03-31",
      start_confirmed: true,
      notes: [],
      fills: 3,
      components: [
        {
          key: "stt",
          label: "STT",
          kind: "value",
          rate: "0.0002",
          rate_text: "0.02% of value",
          side: "sell",
          cap: null,
          gst_on: [],
          per_scrip_day: false,
          note: "",
          source: {
            ...source,
            url: "https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf",
          },
        },
      ],
    },
    {
      effective_from: "2026-04-01",
      effective_to: null,
      start_confirmed: true,
      notes: [],
      fills: 2,
      components: [
        {
          key: "stt",
          label: "STT",
          kind: "value",
          rate: "0.0005",
          rate_text: "0.05% of value",
          side: "sell",
          cap: null,
          gst_on: [],
          per_scrip_day: false,
          note: "",
          source,
        },
      ],
    },
  ],
  notes: [],
  price_bands_checked: false,
  price_bands_note: "Price bands (circuit limits) ... were not checked",
};

describe("A4.2 costs", () => {
  it("lists each dated version's components with a link to the source", () => {
    render(
      <CostsDisclosure
        costs={costs}
        liquidity={{
          adv_cap_pct: 10,
          adv_bars: 20,
          partial_entries: 1,
          skipped_entries: 0,
          not_capped: 0,
          note: "Each buy fills at most 10% ...",
        }}
      />,
    );
    const box = screen.getByTestId("costs-disclosure");
    expect(within(box).getByText(/In force Mar 1, 2026 to Mar 31, 2026/)).toBeInTheDocument();
    expect(within(box).getByText(/In force from Apr 1, 2026/)).toBeInTheDocument();
    expect(within(box).getByText("0.05% of value")).toBeInTheDocument();
    const links = within(box).getAllByRole("link", { name: /NSE\/FATAX/ });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf",
      "https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf",
    ]);
    expect(within(box).getByTestId("price-bands-note")).toBeInTheDocument();
    expect(within(box).getByTestId("costs-before-coverage")).toHaveTextContent("2 fills were");
    expect(within(box).getByRole("link", { name: "Costs and fees" })).toHaveAttribute(
      "href",
      "/docs/costs",
    );
  });

  it("shows the order review net of fees first, each fee with its source", async () => {
    render(
      <form>
        <OrderReview
          mode="market"
          side="buy"
          ticker="TCS.NS"
          quantity="10"
          triggerPrice=""
          currency="INR"
          latestClose={2500}
          closeDate="2026-11-25T00:00:00"
          notional={25000}
          account={{ displayCurrency: "INR", availableCash: 100000 }}
          availableQuantity={0}
        />
      </form>,
    );
    await waitFor(() => expect(screen.getByTestId("order-costs")).toBeInTheDocument());
    expect(screen.getByText("Estimated total, after fees")).toBeVisible();
    expect(screen.getByText("₹25,030.55")).toBeVisible();
    expect(screen.getByText("Value before fees")).toBeVisible();
    const costsBox = screen.getByTestId("order-costs");
    expect(within(costsBox).getByText("Securities transaction tax (STT)")).toBeInTheDocument();
    expect(within(costsBox).getByRole("link", { name: "source" })).toHaveAttribute(
      "href",
      source.url,
    );
  });

  it("formats the helpers", () => {
    expect(partialLabel("100", "1000")).toBe("partial: 100 of 1,000 shares");
    expect(partialLabel("100", null)).toBeNull();
    expect(advCapValue("")).toBeNull();
    expect(advCapValue("0")).toBeNull();
    expect(advCapValue("10")).toBe(10);
    expect(
      versionRange({
        effective_from: "2025-01-01",
        effective_to: "2025-05-13",
        start_confirmed: false,
      }),
    ).toBe("up to May 13, 2025 (start date not confirmed)");
    expect(versionRange({ effective_from: "2024-10-01", effective_to: null })).toBe(
      "from Oct 1, 2024",
    );
    expect(sourceDated(source)).toBe("dated Mar 31, 2026, read Nov 26, 2026");
    expect(
      feesSuffix({ side: "sell", fees: "15.34", net_native: "984.66", currency: "INR" }, (v) =>
        v.toFixed(2),
      ),
    ).toBe(" · fees 15.34 · received 984.66");
    expect(feesSuffix({ side: "buy", fees: "0", net_native: "1", currency: "USD" }, String)).toBe(
      "",
    );
  });
});
