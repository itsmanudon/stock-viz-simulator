import { expect, test } from "@playwright/test";

test("markets page loads and shows at least one symbol row", async ({ page }) => {
  await page.goto("/markets");

  await expect(page.getByRole("heading", { name: "Markets" })).toBeVisible();

  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toBeVisible();

  // Each row has a ticker cell — verify it contains a non-empty string
  const tickerCell = firstRow.locator("td").first();
  const ticker = await tickerCell.innerText();
  expect(ticker.trim().length).toBeGreaterThan(0);
});

test("clicking a market row navigates to the stock page", async ({ page }) => {
  await page.goto("/markets");
  await page.locator("tbody tr").first().waitFor({ state: "visible" });

  const firstRow = page.locator("tbody tr").first();
  const ticker = (await firstRow.locator("td").first().innerText()).trim();

  await firstRow.click();
  await page.waitForURL(`**/stocks/${ticker}**`);

  await expect(page.getByRole("heading", { level: 1 })).toContainText(ticker);
});

test("markets dates its prices by the stored close (audit T1)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/markets");
  const main = page.locator("#main");
  await expect(main.getByText(/latest close [A-Z][a-z]{2} \d{1,2}, \d{4}/)).toBeVisible();
  // Each priced row carries its own close date, year included.
  await expect(main.locator("tbody tr").first()).toContainText(/\d{4}/);
});

test("news speaks to readers, not operators (audit S1)", async ({ page }) => {
  await page.goto("/news");
  const main = page.locator("#main");
  await expect(main).not.toContainText("NEWSDATA_KEY");
  // A pager appears only when there is another page to go to.
  const pager = main.getByRole("navigation", { name: "News pages" });
  if ((await main.getByText(/No stored headlines yet/).count()) > 0) {
    await expect(pager).toHaveCount(0);
  }
});

test("screener filters show as chips and columns sort (audit UX-1)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/screener?rsi_min=0&rsi_max=100&near_52w_low=true");
  const main = page.locator("#main");
  const chips = main.getByRole("list", { name: "Active filters" });
  await expect(chips.getByRole("listitem")).toHaveCount(2);

  // Removing one chip keeps the other filter.
  await chips.getByRole("link", { name: "Remove filter: Near 52-week low" }).click();
  await expect(page).toHaveURL(/rsi_min=0/);
  await expect(page).not.toHaveURL(/near_52w_low/);
  await expect(
    main.getByRole("list", { name: "Active filters" }).getByRole("listitem"),
  ).toHaveCount(1);

  // Sorting keeps the filter, and the first click on a number is biggest first.
  await main.getByRole("link", { name: "RSI(14)" }).click();
  await expect(page).toHaveURL(/sort=rsi&dir=desc/);
  await expect(page).toHaveURL(/rsi_min=0/);
  await expect(main.locator('th[aria-sort="descending"]')).toContainText("RSI");
});
