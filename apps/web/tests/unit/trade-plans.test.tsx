import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  type PlanFormState,
  type TradePlan,
  emptyPlanForm,
  planBadge,
  planFigures,
  planFormFields,
  planFromForm,
  splitTags,
} from "@/lib/plans";

vi.mock("@/app/(product)/(authed)/portfolio/plan-actions", () => ({
  updatePlanAction: vi.fn(async () => ({})),
  planOpenPositionAction: vi.fn(async () => ({})),
}));

const { TicketPlanSection, PlanReview } = await import("@/components/ticket-plan");
const { TradePlansPanel } = await import("@/components/plans/trade-plans-panel");

const FORM: PlanFormState = {
  ...emptyPlanForm("150", "10"),
  enabled: true,
  stop: "140",
  target: "175",
  tags: "breakout, Breakout, base",
};

function plan(overrides: Partial<TradePlan> = {}): TradePlan {
  return {
    id: 1,
    source: "paper",
    book_id: 3,
    replay_session_id: null,
    ticker: "AAPL",
    currency: "USD",
    side: "long",
    planned_entry: "150.000000",
    planned_stop: "140.000000",
    planned_target: "175.000000",
    planned_size: "10.000000",
    risk_per_share: "10.000000",
    planned_risk: "100.000000",
    reward_per_share: "25.000000",
    reward_risk: "2.50",
    setup_version_id: null,
    setup_label: null,
    thesis_id: null,
    thesis_title: null,
    thesis_text: null,
    why: "Tight base",
    invalidation: null,
    horizon_bars: null,
    confidence: null,
    notes: null,
    tags: [],
    status: "active",
    locked: true,
    locked_at: "2025-04-10T20:00:00",
    first_fill_at: "2025-04-10T20:00:00",
    written_after_entry: false,
    frozen: true,
    fills: 1,
    created_at: "2025-04-10T19:59:00",
    updated_at: "2025-04-10T20:00:00",
    ...overrides,
  };
}

describe("plan figures", () => {
  it("works out risk, reward and R:R", () => {
    const f = planFigures(FORM);
    expect(f).toMatchObject({ riskPerShare: 10, risk: 100, reward: 25, rewardRisk: 2.5 });
    expect(f.problem).toBeNull();
  });

  it("names the first problem", () => {
    expect(planFigures({ ...FORM, stop: "155" }).problem).toMatch(/stop must be below/);
    expect(planFigures({ ...FORM, target: "120" }).problem).toMatch(/target must be above/);
    expect(planFigures({ ...FORM, size: "" }).problem).toMatch(/size/);
    expect(planFigures({ ...FORM, target: "" }).problem).toBeNull(); // target optional
  });

  it("de-duplicates tags ignoring case", () => {
    expect(splitTags("breakout, Breakout ,  base  x,")).toEqual(["breakout", "base x"]);
  });
});

describe("the ticket's plan fields", () => {
  it("round-trips through the form fields the server action reads", () => {
    const data = new FormData();
    for (const [k, v] of Object.entries(planFormFields(FORM))) data.set(k, v);
    expect(planFromForm(data)).toEqual({
      side: "long",
      planned_entry: "150",
      planned_stop: "140",
      planned_target: "175",
      planned_size: "10",
      setup_version_id: null,
      thesis_id: null,
      thesis_text: null,
      why: null,
      tags: ["breakout", "base"],
    });
  });

  it("is off unless enabled, and refuses an invalid plan", () => {
    expect(planFormFields({ ...FORM, enabled: false })).toEqual({});
    expect(planFromForm(new FormData())).toBeNull();
    const data = new FormData();
    for (const [k, v] of Object.entries(planFormFields({ ...FORM, stop: "160" }))) data.set(k, v);
    expect(planFromForm(data)).toEqual({
      error: "Plan: A long plan's stop must be below its entry",
    });
  });

  it("starts from the order's price and quantity and shows the figures", async () => {
    function Harness() {
      const [form, setForm] = useState(emptyPlanForm());
      return (
        <TicketPlanSection
          form={form}
          onChange={setForm}
          ticker="AAPL"
          currency="USD"
          referencePrice="150"
          quantity="10"
          options={{
            setups: [{ versionId: 7, label: "Breakout v2" }],
            theses: [
              { id: 4, ticker: "AAPL", title: "Services margin" },
              { id: 5, ticker: "MSFT", title: "Other" },
            ],
          }}
        />
      );
    }
    render(<Harness />);
    await userEvent.click(screen.getByRole("checkbox", { name: /plan this trade/i }));
    expect(screen.getByLabelText("Planned entry")).toHaveValue(150);
    expect(screen.getByLabelText("Size (shares)")).toHaveValue(10);
    await userEvent.type(screen.getByLabelText("Stop"), "140");
    await userEvent.type(screen.getByLabelText("Target (optional)"), "175");
    const figures = screen.getByTestId("ticket-plan-figures");
    expect(figures).toHaveTextContent("$100.00");
    expect(figures).toHaveTextContent("2.50 : 1");
    expect(screen.getByRole("option", { name: "Breakout v2" })).toBeInTheDocument();
    // Only this ticker's theses.
    expect(screen.getByRole("option", { name: "Services margin" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Other" })).toBeNull();
  });

  it("reviews the plan with its risk and R:R and posts it", () => {
    const { container } = render(
      <form>
        <PlanReview form={FORM} currency="USD" quantity="5" options={null} />
      </form>,
    );
    const review = screen.getByTestId("review-plan");
    expect(review).toHaveTextContent("Risk if stopped");
    expect(review).toHaveTextContent("$100.00");
    expect(review).toHaveTextContent("2.50 : 1");
    expect(review).toHaveTextContent("This order is 5 of the 10 planned shares");
    const posted = new FormData(container.querySelector("form") as HTMLFormElement);
    expect(posted.get("plan_enabled")).toBe("1");
    expect(posted.get("plan_stop")).toBe("140");
  });
});

describe("the plans list", () => {
  it("labels locked, written-after-entry and unfilled plans", () => {
    expect(planBadge(plan()).label).toBe("Locked");
    expect(planBadge(plan({ locked: false, written_after_entry: true })).label).toBe(
      "Written after entry",
    );
    expect(planBadge(plan({ locked: false, status: "open", frozen: false })).label).toBe(
      "Not filled yet",
    );
    render(
      <TradePlansPanel
        bookId={3}
        writable
        positions={[]}
        plans={[
          plan(),
          plan({
            id: 2,
            ticker: "MSFT",
            locked: false,
            locked_at: null,
            written_after_entry: true,
          }),
        ]}
      />,
    );
    const rows = screen.getAllByTestId("plan-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Locked");
    expect(rows[1]).toHaveTextContent("Written after entry");
    expect(rows[1]).toHaveTextContent(/left out of plan-adherence/);
    // A frozen plan offers notes and tags only.
    expect(rows[0].querySelector('input[name="stop"]')).toBeNull();
    expect(rows[0].querySelector('textarea[name="notes"]')).not.toBeNull();
  });

  it("points to the ticket when the book has none", () => {
    render(<TradePlansPanel bookId={3} writable positions={[]} plans={[]} />);
    expect(screen.getByRole("link", { name: "order ticket" })).toHaveAttribute(
      "href",
      "/trade?book=3",
    );
  });
});
