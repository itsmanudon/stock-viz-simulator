import { expect, test } from "@playwright/test";

test("research navigation keeps compare, backtest, and signals as one domain", async ({ page }) => {
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
  await expect(product.getByRole("link", { name: "Signals" })).toHaveAttribute(
    "href",
    "/recommendations",
  );

  const subnav = page.getByRole("navigation", { name: "Research tools" });
  await expect(subnav.getByRole("link", { name: "Compare" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Select symbols to compare" })).toBeVisible();
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

test("signals page exposes explainable evidence rather than an AI buy list", async ({ page }) => {
  await page.goto("/recommendations");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Signals", exact: true })).toBeVisible();
  await expect(main.getByText(/not an AI recommendation/i)).toBeVisible();
  await expect(main.locator('select[name="signal"]')).toBeVisible();
  await expect(main.getByRole("region", { name: "Signals list" })).toBeVisible();
});

test("signals selection opens a shareable master-detail evidence workspace", async ({ page }) => {
  await page.goto("/recommendations?sort=ticker&dir=asc");
  const main = page.locator("#main");

  const apple = main.getByRole("button", { name: /AAPL, Apple/i });
  await expect(apple).toBeVisible();
  await apple.click();

  await expect(page).toHaveURL(/\/recommendations\?sort=ticker&dir=asc&selected=AAPL/);
  await expect(main.getByRole("heading", { name: "Seven vote checks" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Open AAPL workspace" })).toBeVisible();
  await expect(main.locator("details")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(main.getByRole("button", { name: "Back to signals" })).toBeVisible();
  await main.getByRole("button", { name: "Back to signals" }).click();
  await expect(page).toHaveURL(/\/recommendations\?sort=ticker&dir=asc$/);
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

  test("signals give the company name the free width (audit D2)", async ({ page }) => {
    await page.goto("/recommendations");
    const row = page.locator("[data-signal-ticker]").first();
    if ((await row.count()) === 0) test.skip(true, "No stored signals");
    const name = row.locator("span.truncate").first();
    const box = await name.boundingBox();
    expect(box && box.width > 150).toBe(true);
  });

  test("backtest's default run produces a result (audit F1)", async ({ page }) => {
    await page.goto("/backtest");
    await expect(page.getByText(/Stored closes for \S+ end/)).toBeVisible();
    await page.getByRole("button", { name: "Run backtest" }).click();
    await expect(page.getByRole("heading", { name: "Equity curve" })).toBeVisible();
  });
});
