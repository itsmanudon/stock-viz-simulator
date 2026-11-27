import { expect, test } from "@playwright/test";

// A7.10 (M5.5): the filings page lists a symbol's documents and searches text
// (the e2e database stores none, so it shows the empty states).
test("the filings page lists and searches stored documents", async ({ page }) => {
  await page.goto("/filings");
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { name: "Filings", exact: true })).toBeVisible();
  await expect(main.getByTestId("filings-intro")).toBeVisible();
  await page.goto("/filings?ticker=AAPL");
  await expect(main.getByTestId("filings-empty")).toBeVisible();
  await page.goto("/filings?q=revenue");
  await expect(main.getByText('No stored document contains "revenue".')).toBeVisible();
  // A8.4: passage search (the e2e database stores no documents either).
  await page.goto("/filings?q=revenue&match=meaning");
  const passages = main.getByTestId("filings-passages");
  await expect(passages).toBeVisible();
  await expect(passages.getByText('No stored passage matches "revenue".')).toBeVisible();
  await expect(main.getByLabel("Match")).toHaveValue("meaning");
});
