import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/rules", () => ({
  checkRule: vi.fn(async (rule: string) => ({
    valid: true,
    canonical: rule,
    hash: "h",
    type: "boolean series",
    warmup_bars: 50,
    warmup_whole_history: false,
    uses: [],
    user_scoped: false,
  })),
}));

import { EventStudyForm } from "@/components/event-study/event-study-form";
import { ScanStudyView } from "@/components/event-study/scan-study-view";
import {
  type ScanStudy,
  eventStudyHref,
  parseStudyParams,
  signedPct,
  studyRequest,
} from "@/lib/event-study";

function study(): ScanStudy {
  const enough = {
    horizon: 20,
    n: 1795,
    symbols: 25,
    incomplete: 16,
    overlapping: 1006,
    enough: true,
    base_rate: 0.0154,
    mean_net: 0.0166,
    median_net: 0.0177,
    mean_excess: 0.0004,
    median_excess: -0.0017,
    hit_rate: 0.6006,
    hit_rate_excess: 0.4919,
    t_stat: 0.2169,
    t_stat_clustered: 0.2148,
    clusters: 1005,
    net_percentiles: { p5: -0.1, p25: -0.02, p50: 0.017, p75: 0.05, p95: 0.13 },
    histogram: { edges: [-0.2, -0.1, 0, 0.1, 0.2], counts: [10, 400, 900, 485] },
    fee_schedules: { us_equity: 1795 },
  };
  return {
    trigger: {
      text: "close crosses_above sma(close, 50)",
      canonical: "close crosses_above sma(close, 50)",
      hash: "h",
      uses: [],
    },
    source: { kind: "market", market: "US", name: "US listings", tickers: 107 },
    from: "2016-11-27",
    to: "2026-11-25",
    cooldown: 0,
    horizons: [
      { ...enough, horizon: 5, n: 12, enough: false, histogram: null, mean_net: null },
      enough,
    ],
    min_events: 30,
    events_found: 1811,
    events_skipped_cooldown: 0,
    events: [
      { ticker: "V", date: "2025-03-31", net: { "5": -0.1088, "20": null }, excess: {} },
      { ticker: "PG", date: "2025-03-28", net: { "5": 0.02, "20": 0.03 }, excess: {} },
    ],
    events_shown: 2,
    method: { event: "First session true after false.", base_rate: "All symbol-days." },
    universe: { name: "pinned", point_in_time: false, survivorship_biased: true, note: "n" },
    disclaimer: "Association, not cause: what followed the trigger in past data.",
  } as unknown as ScanStudy;
}

describe("event study URL state", () => {
  it("parses the URL into a request and back into a link", () => {
    const p = parseStudyParams({ rule: "close > 1", tickers: "aapl, msft", cooldown: "5" });
    expect(p.universe).toBe("tickers");
    expect(studyRequest(p)).toEqual({
      trigger: { rule: "close > 1" },
      universe: { tickers: ["AAPL", "MSFT"] },
      from: null,
      to: null,
      cooldown: 5,
    });
    const setup = parseStudyParams({ setup: "12", market: "IN", from: "2020-01-01" });
    expect(studyRequest(setup)).toMatchObject({
      trigger: { setup_version_id: 12 },
      universe: { market: "IN" },
      from: "2020-01-01",
    });
    expect(studyRequest(parseStudyParams({}))).toBeNull();
    expect(parseStudyParams({ cooldown: "-3", from: "bad" })).toMatchObject({
      cooldown: 0,
      from: "",
    });
    expect(eventStudyHref({ rule: "rsi(14) < 30" })).toBe("/event-study?rule=rsi%2814%29+%3C+30");
    expect(eventStudyHref({ setup: 7 })).toBe("/event-study?setup=7");
    expect(signedPct(0.0123)).toBe("+1.23%");
  });
});

describe("ScanStudyView", () => {
  it("shows counts only under the minimum, figures above it, and linked events", () => {
    render(<ScanStudyView study={study()} />);
    const cards = screen.getAllByTestId("scan-horizon");
    expect(cards[0].getAttribute("data-enough")).toBe("false");
    expect(within(cards[0]).getByTestId("scan-too-few").textContent).toContain("12 of the 30");
    expect(within(cards[1]).getByText("+1.66%")).toBeTruthy();
    expect(within(cards[1]).getByText("60.1%")).toBeTruthy();
    expect(within(cards[1]).getByRole("img").getAttribute("aria-label")).toContain("20-session");
    expect(screen.getByTestId("scan-disclaimer").textContent).toContain("Association, not cause");
    expect(screen.getByRole("link", { name: "V" }).getAttribute("href")).toBe("/stocks/V");
    expect(screen.getByTestId("scan-events").textContent).toContain("-10.9%");
  });
});

describe("EventStudyForm", () => {
  it("fills a preset trigger and keeps the study in GET fields", async () => {
    const { container } = render(
      <EventStudyForm
        initial={parseStudyParams({ rule: "close > 1" })}
        setups={[
          { versionId: 3, name: "Breakout", rule: "close > highest(high, 20)[1]", preset: true },
        ]}
        watchlists={[]}
        signedIn={false}
      />,
    );
    const form = container.querySelector("form") as HTMLFormElement;
    expect(form.getAttribute("method")).toBe("GET");
    await userEvent.click(screen.getByRole("button", { name: "Negative news that day" }));
    const rule = form.querySelector('input[name="rule"]') as HTMLInputElement;
    expect(rule.value).toBe('news.count(1, sentiment="negative") >= 1');
    await userEvent.selectOptions(screen.getByLabelText(/Load a setup/), "3");
    expect((form.querySelector('input[name="setup"]') as HTMLInputElement).value).toBe("3");
    expect(form.querySelector('input[name="rule"]')).toBeNull();
    expect(screen.getByRole("radio", { name: "Watchlist" })).toHaveProperty("disabled", true);
  });
});
