import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  type LaunchForm,
  buildDeckRequest,
  deckScoreLine,
  drillLaunchHref,
  launchProblem,
  parseTickers,
  planRisk,
  scoreLabel,
  universeLabel,
} from "@/lib/drills";

vi.mock("@/app/(product)/(authed)/drills/actions", () => ({
  savePlanAction: vi.fn(async () => ({})),
  revealDrillAction: vi.fn(async () => ({})),
  deleteDeckAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/(authed)/replay/actions", () => ({
  submitReplayOrderAction: vi.fn(async () => ({})),
  cancelReplayOrderAction: vi.fn(async () => ({})),
  advanceReplayAction: vi.fn(async () => ({})),
  cancelReplayAction: vi.fn(async () => ({})),
}));

const { DrillPlanForm } = await import("@/components/drills/drill-plan-form");
const { DrillRevealButton } = await import("@/components/drills/drill-reveal");
const { DeleteDeckButton } = await import("@/components/drills/delete-deck");
const { DrillRevealPanel } = await import("@/components/drills/drill-reveal-panel");
const { ReplayTradeTicket } = await import("@/components/replay-trade-ticket");
const { ReplayAdvanceControls } = await import("@/components/replay-controls");

const FORM: LaunchForm = {
  name: "",
  rule: "close crosses_above sma(close, 50)",
  setupVersionId: "",
  universe: "market",
  market: "US",
  tickers: "",
  watchlistId: "",
  from: "",
  to: "",
  k: "5",
  lead: "60",
  follow: "40",
  seed: "",
  anonymised: true,
};

describe("A4.7 drills: the launch form", () => {
  it("links from the entry points with the rule and universe", () => {
    expect(drillLaunchHref({ rule: "close > 1", market: "US" })).toBe(
      "/drills/new?rule=close+%3E+1&market=US",
    );
    expect(drillLaunchHref({ setupVersionId: 7, rule: "ignored", tickers: ["AAPL", "MSFT"] })).toBe(
      "/drills/new?setup_version_id=7&tickers=AAPL%2CMSFT",
    );
    expect(drillLaunchHref({ rule: "x", watchlistId: 3, from: "2020-01-01" })).toBe(
      "/drills/new?rule=x&watchlist_id=3&from=2020-01-01",
    );
  });

  it("checks K, the bars and the universe", () => {
    expect(launchProblem(FORM)).toBeNull();
    expect(launchProblem({ ...FORM, rule: "" })).toMatch(/rule/);
    expect(launchProblem({ ...FORM, k: "26" })).toMatch(/1 to 25/);
    expect(launchProblem({ ...FORM, k: "0" })).toMatch(/1 to 25/);
    expect(launchProblem({ ...FORM, lead: "4" })).toMatch(/Lead-in/);
    expect(launchProblem({ ...FORM, universe: "tickers", tickers: " " })).toMatch(/ticker/);
    expect(launchProblem({ ...FORM, universe: "watchlist" })).toMatch(/watchlist/);
    expect(launchProblem({ ...FORM, from: "2024-02-01", to: "2024-01-01" })).toMatch(/before/);
    expect(launchProblem({ ...FORM, seed: "abc" })).toMatch(/seed/);
  });

  it("builds the API body, anonymised by default", () => {
    expect(buildDeckRequest(FORM)).toEqual({
      name: null,
      rule: { rule: FORM.rule },
      universe: { market: "US" },
      from: null,
      to: null,
      k: 5,
      lead_bars: 60,
      follow_bars: 40,
      seed: null,
      anonymised: true,
    });
    const b = buildDeckRequest({
      ...FORM,
      setupVersionId: "9",
      universe: "tickers",
      tickers: "aapl, msft aapl",
      seed: "42",
      anonymised: false,
    });
    expect(b.rule).toEqual({ setup_version_id: 9 });
    expect(b.universe).toEqual({ tickers: ["AAPL", "MSFT"] });
    expect(b.seed).toBe(42);
    expect(b.anonymised).toBe(false);
    expect(parseTickers("a,b  c")).toEqual(["A", "B", "C"]);
  });
});

describe("A4.7 drills: scores and decks", () => {
  const score = {
    checks: [],
    passed: 2,
    applicable: 3,
    followed_plan: false,
    traded: true,
    r_achieved: -0.5,
    r_note: "R achieved is shown for reference. It is not the score: the score is the process.",
    total_pnl: "-25.000000",
    rules: {},
  };

  it("words the score on process", () => {
    expect(scoreLabel(score)).toBe("2 of 3 checks");
    expect(scoreLabel({ ...score, traded: false })).toBe("No trade");
    expect(scoreLabel(null)).toBe("—");
    const summary = {
      drills: 5,
      not_started: 2,
      in_progress: 1,
      revealed: 2,
      traded: 2,
      followed_plan: 1,
      checks_passed: 4,
      checks_applicable: 6,
    };
    expect(deckScoreLine(summary)).toBe(
      "1 of 2 traded drills followed the plan · 4 of 6 checks passed",
    );
    expect(deckScoreLine({ ...summary, revealed: 0 })).toBe("No drill revealed yet");
    expect(universeLabel({ market: "US", source_name: "US listings" })).toBe("US listings");
    expect(universeLabel({ tickers: ["A", "B"] })).toBe("2 tickers");
  });

  it("computes the planned risk, long only", () => {
    expect(planRisk(100, 95, 10)).toBe(50);
    expect(planRisk(100, 101, 10)).toBeNull();
    expect(planRisk(100, 95, 0)).toBeNull();
  });

  it("shows the planned risk and refuses a stop above the entry", async () => {
    render(
      <DrillPlanForm
        drillId={3}
        plan={null}
        currentClose="100"
        cash="100000"
        currency="USD"
        readOnly={false}
      />,
    );
    const size = screen.getByTestId("plan-size");
    await userEvent.type(size, "10");
    expect(screen.getByTestId("plan-risk").textContent).toMatch(/\$50\.00/);
    const stop = screen.getByTestId("plan-stop");
    await userEvent.clear(stop);
    await userEvent.type(stop, "120");
    expect(screen.getByTestId("plan-risk").textContent).toMatch(/below the entry/);
    expect(screen.getByTestId("plan-save")).toBeDisabled();
  });

  it("shows a locked plan read-only", () => {
    render(
      <DrillPlanForm
        drillId={3}
        plan={{
          side: "long",
          planned_entry: "100",
          planned_stop: "95",
          planned_size: "10",
          planned_risk: "50",
          note: null,
          locked: true,
          locked_at: "2020-01-01T00:00:00",
        }}
        currentClose="100"
        cash="1000"
        currency="USD"
        readOnly={false}
      />,
    );
    expect(screen.getByTestId("drill-plan").dataset.locked).toBe("true");
    expect(screen.queryByTestId("plan-save")).toBeNull();
  });

  it("asks twice before ending a drill early or deleting a deck", async () => {
    render(<DrillRevealButton drillId={1} finished={false} />);
    expect(screen.queryByTestId("drill-reveal")).toBeNull();
    await userEvent.click(screen.getByTestId("drill-end-early"));
    expect(screen.getByTestId("drill-reveal")).toHaveTextContent("End and reveal");
    render(<DeleteDeckButton deckId={4} drills={5} />);
    await userEvent.click(screen.getByTestId("deck-delete"));
    expect(screen.getByTestId("deck-delete-confirm")).toHaveTextContent("its 5 drills");
  });

  it("sends drill orders and steps to the drill routes", () => {
    const { container } = render(
      <>
        <ReplayTradeTicket
          sessionId={9}
          ticker="Stock A"
          currentClose="10"
          cash="1000"
          quantityHeld="0"
          readOnly={false}
          target="drill"
        />
        <ReplayAdvanceControls
          sessionId={9}
          currentAt="2019-01-01T00:00:00"
          hasNext
          readOnly={false}
          target="drill"
        />
      </>,
    );
    const targets = [...container.querySelectorAll('input[name="target"]')].map(
      (i) => (i as HTMLInputElement).value,
    );
    expect(targets).toEqual(["drill", "drill"]);
    expect(screen.getByText(/drill ticket/)).toBeInTheDocument();
    expect(screen.queryByText("Cancel replay")).toBeNull();
  });

  it("reveals the symbol, the real dates, what followed and R as not the score", () => {
    render(
      <DrillRevealPanel
        reveal={{
          ticker: "AAPL",
          name: "Apple Inc.",
          sector: "Technology",
          currency: "USD",
          trigger_date: "2024-03-04",
          session_start: "2023-12-01",
          session_end: "2024-05-01",
          shown_trigger_date: "2022-03-07",
          date_offset_weeks: 104,
          after: [
            { bars: 5, date: "2024-03-11", close: "110", return_pct: 2.5 },
            { bars: 20, date: null, close: null, return_pct: null },
          ],
          next_bars: [],
        }}
        score={{
          ...score,
          checks: [
            { key: "entry", label: "Entry", status: "passed", detail: "First buy at 100." },
            { key: "stop", label: "Stop", status: "failed", detail: "Held below the stop." },
            { key: "size", label: "Size", status: "not_applicable", detail: "-" },
          ],
        }}
        sessionId={12}
        currency="USD"
      />,
    );
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/104 weeks earlier/)).toBeInTheDocument();
    expect(screen.getByTestId("drill-after")).toHaveTextContent("+2.50%");
    expect(screen.getAllByTestId("drill-check").map((c) => c.dataset.status)).toEqual([
      "passed",
      "failed",
      "not_applicable",
    ]);
    expect(screen.getByTestId("drill-r")).toHaveTextContent("It is not the score");
  });
});
