import { type Page, expect, test } from "@playwright/test";

/**
 * Captures the screenshots the /docs pages show, from the real app (run by
 * playwright.docs.config.ts against a seeded local stack, never in CI).
 * One sign-up; each image is one element, so page chrome stays out of it.
 */

const OUT = "public/docs";

/** The top of #main, for pages too long to capture whole. */
async function topOf(page: Page, path: string, height = 820) {
  const box = await page.locator("#main").boundingBox();
  if (!box) throw new Error(`no #main for ${path}`);
  await page.screenshot({ path, clip: { x: box.x, y: box.y, width: box.width, height } });
}

/** Element screenshots scroll; a sticky top bar would sit over them. */
async function go(page: Page, url: string) {
  await page.goto(url);
  await page.addStyleTag({ content: "header.sticky { position: static !important; }" });
}
test.use({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });

test("capture the docs screenshots", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Docs Screens");
  await page.getByLabel("Email").fill(`docs+${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
  const main = page.locator("#main");

  // Shares to cover a call, and a market buy under review for the Orders page.
  await go(page, "/trade?ticker=AAPL");
  await main.getByLabel("Quantity").fill("100");
  await main.getByRole("button", { name: /Review market buy/i }).click();
  await main
    .getByRole("region", { name: "Order ticket" })
    .screenshot({ path: `${OUT}/order-review.png` });
  await main.getByRole("button", { name: /Place market buy/i }).click();
  await expect(main.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled BUY",
    { timeout: 15_000 },
  );

  // The single-contract option ticket with its quote and Greeks.
  await go(page, "/trade?ticker=AAPL");
  await main.locator("#opt-ticker").selectOption("AAPL");
  await expect(main.getByLabel("Greeks")).toContainText("Delta", { timeout: 15_000 });
  await main
    .locator("#opt-ticker")
    .locator("xpath=ancestor::form[1]")
    .screenshot({
      path: `${OUT}/option-ticket.png`,
    });

  // The strategy builder with a bull call spread, then open it and a covered call.
  const builder = main.getByRole("region", { name: "Strategy builder" });
  await builder.getByLabel("Underlying").selectOption("AAPL");
  await expect(builder.getByRole("region", { name: "Strategy figures" })).toContainText(
    "Most it can lose",
    { timeout: 15_000 },
  );
  await builder.screenshot({ path: `${OUT}/strategy-builder.png` });
  await builder.getByRole("button", { name: "Review strategy" }).click();
  await builder.getByRole("button", { name: "Place bull call spread" }).click();
  await expect(builder.getByText(/Opened a bull call spread/)).toBeVisible({ timeout: 15_000 });
  await builder.getByLabel("Strategy", { exact: true }).selectOption("covered_call");
  await expect(builder.getByRole("region", { name: "Strategy figures" })).toContainText(
    "Shares used",
    { timeout: 15_000 },
  );
  await builder.getByRole("button", { name: "Review strategy" }).click();
  await builder.getByRole("button", { name: "Place covered call" }).click();
  await expect(builder.getByText(/Opened a covered call/)).toBeVisible({ timeout: 15_000 });

  // The portfolio's options book.
  await go(page, "/portfolio?tab=options");
  await expect(main.getByRole("region", { name: "Expirations" })).toBeVisible();
  await main.getByRole("region", { name: "Options Greeks" }).screenshot({
    path: `${OUT}/options-book.png`,
  });

  // The risk panel, on the shares and options bought above.
  await go(page, "/portfolio?tab=analytics");
  const risk = page.locator('#main section[aria-labelledby="risk-heading"]');
  await expect(risk).toContainText(/VaR|value at risk/i, { timeout: 20_000 });
  await risk.screenshot({ path: `${OUT}/risk-panel.png` });

  // The screener, top of the page.
  await go(page, "/screener");
  await expect(main.getByRole("table").first()).toBeVisible({ timeout: 15_000 });
  const box = await main.boundingBox();
  if (box) {
    await page.screenshot({
      path: `${OUT}/screener.png`,
      clip: { x: box.x, y: box.y, width: box.width, height: 820 },
    });
  }

  // A backtest result.
  await go(page, "/backtest?ticker=AAPL");
  await main.getByRole("button", { name: "Run backtest" }).click();
  const curve = main.getByRole("heading", { name: "Equity curve" });
  await expect(curve).toBeVisible({ timeout: 20_000 });
  await curve.locator("xpath=ancestor::section[1]").screenshot({ path: `${OUT}/backtest.png` });

  // A watchlist and an alert, so Home shows them.
  await go(page, "/watchlist");
  for (const ticker of ["MSFT", "NVDA"]) {
    await main.getByLabel("Add symbol").fill(ticker);
    await main.getByRole("button", { name: "Add to watchlist" }).click();
    await expect(main.getByRole("link", { name: ticker }).first()).toBeVisible();
  }
  await go(page, "/alerts?ticker=AAPL");
  const create = main.getByRole("region", { name: "Create alert" });
  await create.getByLabel("Target (USD)").fill("200");
  await create.getByRole("button", { name: "Create alert" }).click();
  await expect(create.getByText("Alert set.")).toBeVisible();

  // Alerts, the portfolio, compare and the checklist: the top of each page.
  await go(page, "/alerts");
  await expect(main.getByRole("list", { name: "Alert rules" })).toContainText("AAPL");
  await topOf(page, `${OUT}/alerts.png`, 700);
  await go(page, "/portfolio");
  await expect(main.getByText("AAPL").first()).toBeVisible();
  await topOf(page, `${OUT}/portfolio.png`);
  await go(page, "/compare?tickers=AAPL&tickers=MSFT&tickers=NVDA&tf=1Y");
  await page.waitForLoadState("networkidle");
  await topOf(page, `${OUT}/compare.png`);
  await go(page, "/checklist");
  await page.waitForLoadState("networkidle");
  await topOf(page, `${OUT}/checklist.png`, 760);

  // A replay session after one buy.
  await go(page, "/replay");
  await main.getByLabel("Symbol").selectOption("AAPL");
  await expect(main.getByText(/Stored daily bars for AAPL/i)).toBeVisible({ timeout: 10_000 });
  await main.getByLabel("Start date").fill("2020-01-06");
  await main.getByLabel("End date").fill("2020-01-31");
  await main.getByRole("button", { name: "Start replay" }).click();
  await expect(page).toHaveURL(/\/replay\/\d+/, { timeout: 15_000 });
  await page.addStyleTag({ content: "header.sticky { position: static !important; }" });
  await main
    .locator("aside")
    .getByRole("button", { name: /Submit market buy/i })
    .click();
  await expect(main.getByText(/Filled BUY/i)).toBeVisible({ timeout: 10_000 });
  await topOf(page, `${OUT}/replay.png`);

  // Home.
  await go(page, "/dashboard");
  await page.waitForLoadState("networkidle");
  await main.screenshot({ path: `${OUT}/dashboard.png` });
});
