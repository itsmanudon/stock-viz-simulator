import { expect, test } from "@playwright/test";

test("research navigation keeps compare, backtest, and the checklist as one domain", async ({
  page,
}) => {
  await page.goto("/compare");

  const product = page.getByRole("navigation", { name: "Product" });
  // Section headings are labels, not links (Aurora app shell, UI batch A).
  await expect(product.getByText("Research", { exact: true })).toHaveAttribute(
    "data-active",
    "true",
  );
  await expect(product.getByRole("link", { name: "Compare" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(product.getByRole("link", { name: "Backtest" })).toHaveAttribute(
    "href",
    "/backtest",
  );
  await expect(product.getByRole("link", { name: "Checklist" })).toHaveAttribute(
    "href",
    "/checklist",
  );

  const subnav = page.getByRole("navigation", { name: "Research tools" });
  await expect(subnav.getByRole("link", { name: "Compare" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  // Scoped to #main for the same reason as the backtest test below.
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Select symbols to compare" })).toBeVisible();
});

test("compare query params drive the workspace", async ({ page }) => {
  await page.goto("/compare?tickers=AAPL&tf=3M");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(main.getByRole("link", { name: "3M" })).toBeVisible();
  await expect(main.getByRole("link", { name: "AAPL" }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );
  await expect(main.locator('a[href="/backtest?ticker=AAPL"]')).toBeVisible();
});

test("backtest is an experiment workspace with visible assumptions", async ({ page }) => {
  await page.goto("/backtest?ticker=AAPL");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Backtest", exact: true })).toBeVisible();
  await expect(main.getByLabel("Symbol")).toHaveValue("AAPL");
  await expect(main.getByRole("heading", { name: "No experiment yet" })).toBeVisible();
  await expect(main.getByLabel("Commission (bps)")).toBeVisible();
  await expect(
    main.getByRole("region", { name: "Strategy setup" }).getByText(/look-ahead bias/i),
  ).toBeVisible();
});

test("the checklist shows each dimension with its formula, not a buy list", async ({ page }) => {
  await page.goto("/checklist");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Checklist", exact: true })).toBeVisible();
  await expect(main.getByText(/not a recommendation/i).first()).toBeVisible();
  await expect(main.getByRole("heading", { name: "The six dimensions" })).toBeVisible();
  await main.getByTestId("dimension-trend").locator("summary").click();
  await expect(
    main.getByTestId("dimension-trend").getByText("close > sma(close, 200)"),
  ).toBeVisible();
  await expect(main).not.toContainText(/\b(bullish|bearish|strong buy)\b/i);
});

test("an old Signals link lands on the checklist with its ticker search", async ({ page }) => {
  await page.goto("/recommendations?q=AAPL");
  await expect(page).toHaveURL(/\/checklist\?q=AAPL$/);
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Checklist", exact: true })).toBeVisible();
});

test("checklist filters are shareable links", async ({ page }) => {
  await page.goto("/checklist?min=2&sort=ticker");
  const main = page.locator("#main");
  await expect(main.getByRole("link", { name: "At least 2 of 6" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(main.getByRole("link", { name: "Ticker" })).toHaveAttribute("aria-current", "true");
});

test.describe("research pages on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  // The TradingView attribution logo is required by the chart licence and is
  // not ours to resize, so it is left out.
  test("compare controls are big enough to tap (audit A3)", async ({ page }) => {
    await page.goto("/compare?tickers=AAPL,MSFT");
    const main = page.locator("#main");
    await expect(main.getByRole("button", { name: "Remove AAPL" })).toBeVisible();
    const small = await main
      .locator("a:visible:not(#tv-attr-logo), button:visible")
      .evaluateAll((elements) =>
        elements
          .map((el) => ({
            label: el.textContent?.trim() || el.getAttribute("aria-label"),
            h: el.getBoundingClientRect().height,
          }))
          .filter((item) => item.h > 0 && item.h < 24),
      );
    expect(small).toEqual([]);
  });

  test("checklist cards keep the company name readable (audit D2)", async ({ page }) => {
    await page.goto("/checklist");
    // Scoped to #main: `next start` can briefly keep a second, hidden copy of
    // the page tree, and an unscoped match can pick a card with no box.
    const main = page.locator("#main");
    // count() does not wait: let the page render before deciding to skip.
    await expect(main.getByRole("heading", { name: "Checklist", exact: true })).toBeVisible();
    const card = main.locator('[data-testid^="checklist-row-"]').first();
    if ((await card.count()) === 0) test.skip(true, "No stored checklist scores");
    await expect(card).toBeVisible();
    const box = await card.locator("summary").boundingBox();
    expect(box && box.width > 300).toBe(true);
  });

  test("backtest's default run produces a result (audit F1)", async ({ page }) => {
    await page.goto("/backtest");
    // Scoped to #main: `next start` can briefly keep a second copy of the
    // page tree, and an unscoped match then fails strict mode (PR #94).
    const main = page.locator("#main");
    await expect(main.getByText(/Stored closes for \S+ end/)).toBeVisible();
    await main.getByRole("button", { name: "Run backtest" }).click();
    await expect(main.getByRole("heading", { name: "Equity curve" })).toBeVisible();
  });

  test("backtest's rule strategy mode runs and marks trades on the chart (A4.1)", async ({
    page,
  }) => {
    await page.goto("/backtest?mode=rule&ticker=AAPL");
    const main = page.locator("#main");
    await expect(main.getByTestId("rule-ok")).toHaveCount(2);
    await main.getByRole("button", { name: "Run strategy" }).click();
    await expect(main.getByRole("heading", { name: "Performance, net of costs" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(main.getByTestId("strategy-chart-caption")).toContainText("AAPL:");
    await expect(main.getByRole("heading", { name: "Equity curve" })).toBeVisible();
  });

  test("a rule backtest lists its costs and the ADV cap (A4.2)", async ({ page }) => {
    // stockviz_e2e holds US bars only: a US symbol defaults to no fees, and
    // the disclosure still states the schedule, the cap and its link.
    await page.goto("/backtest?mode=rule&ticker=AAPL");
    const main = page.locator("#main");
    await expect(main.getByTestId("rule-ok")).toHaveCount(2);
    await main.getByRole("button", { name: "Run strategy" }).click();
    await expect(main.getByRole("heading", { name: "Performance, net of costs" })).toBeVisible({
      timeout: 30_000,
    });
    const costs = main.getByTestId("costs-disclosure");
    await expect(costs).toContainText("No fees");
    await costs.locator("summary").click();
    await expect(costs.getByTestId("liquidity-note")).toContainText("20-day average traded value");
    await expect(costs.getByRole("link", { name: "Costs and fees" })).toBeVisible();
  });

  test("a backtest shows its report card and overfitting checks (A4.3)", async ({ page }) => {
    await page.goto("/backtest?ticker=AAPL");
    const main = page.locator("#main");
    await main.getByRole("button", { name: "Run backtest" }).click();
    const card = main.getByTestId("report-card");
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("CAGR")).toBeVisible();
    await card.getByTestId("formula-tip").first().click();
    await expect(card.getByRole("tooltip")).toContainText("365.25");
    const checks = main.getByTestId("overfitting-checks");
    await expect(checks.getByTestId("trials-n")).not.toHaveText("");
    await expect(checks.getByTestId("dsr-meaning")).toContainText("chance");
    // Signed out: the holdout stays locked and cannot be unlocked here.
    await expect(main.getByTestId("holdout-panel")).toHaveAttribute("data-status", "locked");
    await expect(main.getByTestId("holdout-unlock")).toHaveCount(0);
    await expect(main.getByTestId("run-window")).toContainText("held out");
  });
});
