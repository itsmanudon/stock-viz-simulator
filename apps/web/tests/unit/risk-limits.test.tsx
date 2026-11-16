import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LimitPreviewRows } from "@/components/limit-preview";
import { RiskLimitsForm } from "@/components/risk-limits-form";
import { limitsFromForm } from "@/lib/risk-limits";

afterEach(() => vi.unstubAllGlobals());

describe("risk limits (Phase 8.5)", () => {
  it("turns empty or invalid fields into no limit", () => {
    const form = new FormData();
    form.set("max_position_pct", "12.5");
    form.set("max_order_pct", "");
    form.set("max_sector_pct", "0");
    form.set("max_currency_pct", "150");
    form.set("max_var_pct", "abc");
    expect(limitsFromForm(form)).toEqual({
      max_position_pct: "12.5",
      max_order_pct: null,
      max_sector_pct: null,
      max_currency_pct: null,
      max_var_pct: null,
    });
  });

  it("shows the saved limits with empty meaning none", () => {
    render(
      <RiskLimitsForm
        limits={{
          max_position_pct: "10.00",
          max_order_pct: null,
          max_sector_pct: null,
          max_currency_pct: null,
          max_var_pct: null,
        }}
        action={async () => {}}
      />,
    );
    expect((screen.getByLabelText("Largest holding (%)") as HTMLInputElement).value).toBe("10.00");
    expect((screen.getByLabelText("Single order (%)") as HTMLInputElement).value).toBe("");
  });

  it("previews a breach in the order review", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          ticker: "AAPL",
          quantity: "150",
          breached: true,
          checks: [
            {
              limit: "max_position_pct",
              label: "position",
              cap: 10,
              value_after: 15,
              breached: true,
            },
          ],
        }),
      })),
    );
    render(<LimitPreviewRows ticker="AAPL" quantity="150" />);
    await waitFor(() => expect(screen.getByText("15.00% · limit 10.00%")).toBeTruthy());
    expect(screen.getByText(/crosses one of your limits, so it will be refused/)).toBeTruthy();
  });
});
