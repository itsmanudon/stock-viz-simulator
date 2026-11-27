import { expect, test } from "@playwright/test";

// A9.3 (M7.6): the pairs lab runs a cointegration test on two stored symbols.
test("the pairs lab tests two stored symbols", async ({ page }) => {
  await page.goto("/pairs?a=AAPL&b=MSFT&years=3");
  await expect(page.getByRole("heading", { name: "Pairs lab" })).toBeVisible();
  const verdict = page.getByTestId("pair-verdict").or(page.getByText(/Needs \d+ sessions/));
  await expect(verdict).toBeVisible();
  await expect(page.getByText(/MacKinnon|Needs/).first()).toBeVisible();
});
