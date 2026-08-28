import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

// Signup is capped at 5/IP/hour. A retry would consume a sixth attempt and
// mask the original locator error behind a rate-limit timeout.
test.describe.configure({ retries: 0 });

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

// One signup covers the operational loop and Replay Lab. Credential signup is
// capped at 5/IP/hour, and auth + portfolio + stock-workspace consume the other slots.
test("operational trading loop from ticket to orders, watchlist, alerts, and replay", async ({ page }) => {
  const email = `e2e+ops+${Date.now()}@example.com`;
  await signUp(page, email);

  await page.goto("/trade?ticker=AAPL");
  await expect(page.getByRole("heading", { name: "Trade", exact: true })).toBeVisible();
  await expect(page.getByLabel("Symbol")).toHaveValue("AAPL");
  await expect(
    page
      .getByRole("region", { name: "Order ticket" })
      .getByText(/Submits immediately at the latest stored daily close/i),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Account context" }).getByText("Buying power"),
  ).toBeVisible();

  await page.getByLabel("Quantity").fill("1");
  await page.getByRole("button", { name: /Submit market buy/i }).click();
  await expect(page.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled BUY",
    { timeout: 10_000 },
  );
  await expect(page.getByRole("table", { name: "Recent paper fills" })).toContainText("AAPL");

  await page.goto("/trades");
  await expect(page.getByRole("heading", { name: "Trade history" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("BUY");

  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No pending orders" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Order status" }).getByRole("link", { name: "Filled" }),
  ).toHaveAttribute("href", "/orders?status=filled");

  await page.goto("/watchlist");
  await expect(page.getByRole("heading", { name: "Watchlist", exact: true })).toBeVisible();
  await page.getByLabel("Add symbol").selectOption("AAPL");
  await page.getByRole("button", { name: "Add to watchlist" }).click();
  await expect(page.getByRole("link", { name: "AAPL" }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );

  await page.goto("/alerts?ticker=AAPL");
  await expect(page.getByRole("heading", { name: "Alerts", exact: true })).toBeVisible();
  await expect(page.locator("#main header")).toContainText(
    /This is not email, push, or real-time exchange monitoring/i,
  );

  const create = page.getByRole("region", { name: "Create alert" });
  await create.getByLabel("Target price").fill("1");
  await create.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByRole("table", { name: "Price alerts" })).toContainText("AAPL", {
    timeout: 10_000,
  });
  await expect(create.getByText("Alert set.")).toBeVisible();

  const leaked: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/v1/symbols/")) leaked.push(url);
    if (url.includes("/v1/quotes")) leaked.push(url);
    if (url.includes("/v1/stream/quotes")) leaked.push(url);
    if (url.includes("/v1/news")) leaked.push(url);
  });

  await page.goto("/replay");
  await expect(page.getByRole("heading", { name: "Replay", exact: true })).toBeVisible();
  await expect(page.getByText(/legacy_close v1/i)).toBeVisible();
  await page.getByLabel("Symbol").selectOption("AAPL");
  await expect(page.getByText(/Stored daily bars for AAPL/i)).toBeVisible({ timeout: 10_000 });
  await page.getByLabel("Start date").fill("2020-01-04");
  await page.getByLabel("End date").fill("2020-01-19");
  await page.getByRole("button", { name: "Start replay" }).click();
  await expect(page).toHaveURL(/\/replay\/\d+/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
  await expect(page.getByText(/stored sessions 2020-01-04 → 2020-01-19/)).toBeVisible();
  await expect(page.getByText(/Saturday, January 4, 2020/)).toBeVisible();
  await expect(page.getByRole("region", { name: /replay price chart/i })).toBeVisible();
  await expect(
    page.getByRole("region", { name: /replay price chart/i }).getByText("Replay close"),
  ).toBeVisible();
  await expect(page.getByText(/Indicative/i)).toHaveCount(0);

  const desktopTicket = page.locator("aside").getByRole("button", { name: /Submit market buy/i });
  if (await desktopTicket.isVisible()) {
    await desktopTicket.click();
  } else {
    await page.getByRole("button", { name: /Buy AAPL in replay/i }).click();
    await page.getByRole("button", { name: /Submit market buy/i }).click();
  }
  await expect(page.getByText(/Filled BUY/i)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("table", { name: "Replay fills" })).toContainText("AAPL");
  await expect(page.getByRole("heading", { name: "No open replay position." })).toHaveCount(0);

  const before = await page
    .getByRole("heading", { name: "AAPL", exact: true })
    .locator("..")
    .textContent();
  await page.getByRole("button", { name: "Advance to next session" }).click();
  await expect(page.getByText(/Advanced:/i)).toBeVisible({ timeout: 10_000 });
  const after = await page
    .getByRole("heading", { name: "AAPL", exact: true })
    .locator("..")
    .textContent();
  expect(after).not.toEqual(before);
  expect(leaked).toEqual([]);
});
