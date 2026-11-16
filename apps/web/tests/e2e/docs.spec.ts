import { expect, test } from "@playwright/test";

import { DOC_PAGES } from "../../lib/docs/nav";

// The public user guide: every page renders, its screenshots load, the
// navigation works, and nothing scrolls sideways on a phone.

test("the docs overview lists every page and is reachable from the header", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Public" })
    .getByRole("link", { name: "Docs" })
    .click();
  await expect(page).toHaveURL(/\/docs$/);
  const main = page.locator("#main");
  await expect(main.getByRole("heading", { level: 1, name: "StockViz docs" })).toBeVisible();
  for (const doc of DOC_PAGES) {
    await expect(main.getByRole("link", { name: new RegExp(doc.title) }).first()).toBeVisible();
  }
});

for (const doc of DOC_PAGES) {
  test(`docs page ${doc.slug} renders with working screenshots`, async ({ page }) => {
    const response = await page.goto(`/docs/${doc.slug}`);
    expect(response?.status()).toBe(200);
    const main = page.locator("#main");
    await expect(main.getByRole("heading", { level: 1, name: doc.title })).toBeVisible();
    const current = main
      .getByRole("navigation", { name: "Documentation" })
      .last()
      .getByRole("link", { name: doc.title });
    await expect(current).toHaveAttribute("aria-current", "page");
    for (const img of await main.locator("figure img").all()) {
      await img.scrollIntoViewIfNeeded();
      await expect
        .poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0);
    }
  });
}

test("on a phone the contents fold above the page and nothing overflows", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/docs/options");
  const main = page.locator("#main");
  await main.getByText("Contents").click();
  await main
    .getByRole("navigation", { name: "Documentation" })
    .first()
    .getByRole("link", { name: "Orders" })
    .click();
  await expect(page).toHaveURL(/\/docs\/orders$/);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
