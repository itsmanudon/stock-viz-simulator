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

test("news: views, search, keyboard and phone width (news redesign)", async ({ page }) => {
  await page.goto("/news");
  const main = page.locator("#main");
  await expect(main).not.toContainText("NEWSDATA_KEY");
  await expect(main.getByRole("heading", { name: "News", exact: true })).toBeVisible();

  // Listed companies is the default view; general headlines have their own.
  const views = main.getByRole("navigation", { name: "News views" });
  await expect(views.getByRole("link", { name: "Listed Companies" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await views.getByRole("link", { name: "Market Headlines" }).click();
  await expect(page).toHaveURL(/\/news\?scope=market$/);
  await expect(views.getByRole("link", { name: "Market Headlines" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  // The old page's market link still opens the market view.
  await page.goto("/news?view=market");
  await expect(views.getByRole("link", { name: "Market Headlines" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // "/" focuses the headline search on this page (the palette keeps ⌘K).
  await page.goto("/news");
  await expect(main.getByTestId("news-search-shortcut")).toHaveAttribute("data-ready", "true");
  await page.locator("body").press("/");
  await expect(main.getByRole("searchbox", { name: /Search Headlines/ })).toBeFocused();
  await page.keyboard.type("zzqx-no-such-headline");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/q=zzqx-no-such-headline/);
  await expect(main.getByRole("heading", { name: "No headlines match" })).toBeVisible();
  // No pager under an empty list (audit S1).
  await expect(main.getByRole("navigation", { name: "News pages" })).toHaveCount(0);
  await expect(main.getByTestId("news-active-filters")).toBeVisible();

  // Tone chips are links that toggle; the page fits a phone.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/news?sentiment=negative");
  await expect(main.getByRole("link", { name: /^Negative/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflows, "/news scrolls sideways at 390px").toBe(false);
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
  // The sortable table exists only with rows, which need `stockviz.cli metrics`.
  if ((await main.getByText(/No symbols match/).count()) > 0) {
    test.skip(true, "No screener rows: symbol metrics have not been computed");
  }
  await main.getByRole("link", { name: "RSI(14)" }).click();
  await expect(page).toHaveURL(/sort=rsi&dir=desc/);
  await expect(page).toHaveURL(/rsi_min=0/);
  await expect(main.locator('th[aria-sort="descending"]')).toContainText("RSI");
});
