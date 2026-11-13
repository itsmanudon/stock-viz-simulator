import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

test.describe.configure({ retries: 0 });

async function signUp(page: Page, label: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Portfolio Workspace Tester");
  await page.getByLabel("Email").fill(`e2e+portfolio+${label}+${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

test("authenticated user can move from a paper trade into the Portfolio workspace", async ({
  page,
}) => {
  await signUp(page, "populated");

  await page.goto("/trade?ticker=AAPL");
  await expect(page.getByLabel("Symbol")).toHaveValue("AAPL");
  // The ticket reviews before it places (UX-4): open the review, then place.
  await page.getByRole("button", { name: /Review market buy/i }).click();
  await page.getByRole("button", { name: /Place market buy/i }).click();
  await expect(page.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled BUY",
    { timeout: 10_000 },
  );
  await expect(page.getByRole("table", { name: "Recent paper fills" })).toContainText("AAPL");

  await page.goto("/portfolio");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
  await expect(main.getByText("Latest EOD valuation", { exact: false })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Positions/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("table", { name: "Stock positions" })).toBeVisible();
  await expect(page.getByRole("link", { name: "AAPL", exact: true }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );

  await page.getByRole("link", { name: "1Y" }).click();
  await expect(page).toHaveURL(/\/portfolio\?range=1y/);

  await page.getByRole("tab", { name: "Orders" }).click();
  await expect(page).toHaveURL(/range=1y&tab=orders/);
  await expect(page.getByText(/No pending orders across your portfolio/)).toBeVisible();

  await page.getByRole("tab", { name: "Income" }).click();
  await expect(page).toHaveURL(/range=1y&tab=income/);
  await expect(page.getByText("No dividend income has been credited yet.")).toBeVisible();

  // Phase 8.1: returns name their method; a day-old holding has no XIRR yet.
  await page.getByRole("tab", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/range=1y&tab=analytics/);
  await expect(main.getByText(/Method: time-weighted/)).toBeVisible();
  const holdings = main.getByRole("table", { name: "Money-weighted return by holding" });
  await expect(holdings).toContainText("AAPL");
  await expect(holdings).toContainText("held under 30 days");
  // Phase 8.2: exposure weights and the holding's gain split by source.
  await expect(main.getByRole("list", { name: "By sector" })).toBeVisible();
  await expect(main.getByRole("list", { name: "By currency" })).toContainText("USD");
  await expect(main.getByRole("table", { name: "Gain by source" })).toContainText("AAPL");
  // Phase 8.3: risk names its method; seeded history is long enough for VaR.
  await expect(main.getByText(/Method: historical simulation/)).toBeVisible({ timeout: 10_000 });
  await expect(main.getByRole("table", { name: "Value at risk" })).toContainText("95%");
  // Phase 8.4: the fixed shocks always apply; a US stock moves with them.
  await expect(main.getByRole("table", { name: "Fixed shocks" })).toContainText("US stocks -10%");

  // Phase 8.5: a single-order limit set in Settings shows in the review and
  // refuses a buy over it.
  await page.goto("/settings");
  await page.getByLabel("Single order (%)").fill("0.01");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByLabel("Single order (%)")).toHaveValue("0.01");
  await page.goto("/trade?ticker=AAPL");
  await page.getByRole("button", { name: /Review market buy/i }).click();
  await expect(page.getByText(/crosses one of your limits/)).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /Place market buy/i }).click();
  await expect(page.getByText(/over your limit of 0\.01%/)).toBeVisible({ timeout: 10_000 });
});

test("new mobile portfolio keeps value, tabs, and starting actions readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signUp(page, "mobile-empty");
  await page.goto("/portfolio");

  await expect(page.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("$100,000.00", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your portfolio is ready" })).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Portfolio sections" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Explore markets" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Place a trade" })).toBeVisible();

  const hasDocumentOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasDocumentOverflow).toBe(false);

  await page.getByRole("tab", { name: "Options" }).click();
  await expect(page).toHaveURL(/tab=options/);
  await expect(page.getByText("No option positions are currently open.")).toBeVisible();

  // Audit P3, in this test rather than its own: the suite's sign-ups must
  // stay within the web app's limit of 5 an hour, or the last spec's sign-up
  // is refused. On the narrowest phone the active tab is scrolled into view
  // and the edge with more tabs fades.
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/portfolio?tab=journal");
  const row = page.getByRole("tablist", { name: "Portfolio sections" }).locator("..");
  await expect(page.getByRole("tab", { name: "Journal" })).toBeInViewport();
  await expect(row).toHaveAttribute("data-more-start", "true");

  // With room to spare every tab fits, so nothing fades. Seven tabs since
  // Phase 8.1 (Analytics) need 423px, more than a 430px phone leaves them.
  await page.setViewportSize({ width: 480, height: 700 });
  await expect(row).not.toHaveAttribute("data-more-start", "true");
  await expect(row).not.toHaveAttribute("data-more-end", "true");
});
