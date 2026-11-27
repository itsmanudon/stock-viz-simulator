import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

/** A6.7: a right-click inside the stock chart's price pane. */
export async function rightClickChart(page: Page) {
  const chart = page.locator("#main").getByTestId("price-chart").first();
  await expect(chart).toBeVisible();
  const box = await chart.boundingBox();
  if (!box) throw new Error("no chart box");
  await page.mouse.click(box.x + box.width * 0.4, box.y + 80, { button: "right" });
}
