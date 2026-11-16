import { expect, test } from "@playwright/test";

/**
 * Captures the screenshots the /docs pages show, from the real app (run by
 * playwright.docs.config.ts against a seeded local stack, never in CI).
 * One sign-up; each image is one element, so page chrome stays out of it.
 */

const OUT = "public/docs";
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
  await page.goto("/trade?ticker=AAPL");
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
  await page.goto("/trade?ticker=AAPL");
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
  await builder.getByLabel("Strategy").selectOption("covered_call");
  await expect(builder.getByRole("region", { name: "Strategy figures" })).toContainText(
    "Shares used",
    { timeout: 15_000 },
  );
  await builder.getByRole("button", { name: "Review strategy" }).click();
  await builder.getByRole("button", { name: "Place covered call" }).click();
  await expect(builder.getByText(/Opened a covered call/)).toBeVisible({ timeout: 15_000 });

  // The portfolio's options book.
  await page.goto("/portfolio?tab=options");
  await expect(main.getByRole("region", { name: "Expirations" })).toBeVisible();
  await main.getByRole("region", { name: "Options Greeks" }).screenshot({
    path: `${OUT}/options-book.png`,
  });

  // Home.
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await main.screenshot({ path: `${OUT}/dashboard.png` });
});
