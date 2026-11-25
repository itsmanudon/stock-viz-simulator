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
});
