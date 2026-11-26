/**
 * A5.3, A6.11: tradebook imports and the basket handoff, end to end.
 *
 * - A Dhan book takes a Dhan file: the map is detected from the header row and
 *   the "Columns Matched" disclosure names it (unconfirmed).
 * - A file no map reads opens "Map Columns Yourself"; the saved map previews
 *   and imports.
 * - A screen's basket downloads as CSV; with no KITE_API_KEY on the e2e server
 *   there is no Kite button. Nothing calls Kite.
 *
 * Every file here is synthetic: invented trade ids, prices and dates.
 */

import { readFile } from "node:fs/promises";

import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

test.describe.configure({ retries: 0 });

// Signup is capped at 5 per client address an hour (`app/(public)/(auth)/actions.ts`),
// and the other specs use those slots. The address is the hop our proxy adds to
// x-forwarded-for (`lib/client-address.ts`); with no proxy in front of the test
// server, this header stands in for the proxy, so the file's two signups come
// from their own address. A value a client adds ahead of the proxy's is ignored.
test.use({ extraHTTPHeaders: { "x-forwarded-for": "10.61.1.1" } });

async function signUp(page: Page, label: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Import Tester");
  await page.getByLabel("Email").fill(`e2e+imports+${label}+${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

function csv(...lines: string[]) {
  return Buffer.from(`${lines.join("\n")}\n`);
}

test("a Dhan file imports by its detected map, and an unknown file by the user's own map", async ({
  page,
}) => {
  await signUp(page, "maps");

  await page.goto("/settings#books");
  const create = page.getByRole("form", { name: "New book" });
  await create.getByLabel("Name").fill("Dhan Book");
  await create.getByLabel("Kind").selectOption("imported");
  await create.getByLabel("Broker (Imported Books)").selectOption("dhan");
  await create.getByRole("button", { name: "Create book" }).click();
  await expect(page.getByText("Created Dhan Book (INR).")).toBeVisible({ timeout: 10_000 });

  await page.goto("/portfolio/import");
  await page.getByRole("link", { name: "Import into Dhan Book" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Import tradebook" })).toBeVisible();
  await expect(page.getByText("Dhan · INR")).toBeVisible();

  const file = page.getByLabel("Tradebook File");
  await file.setInputFiles({
    name: "dhan.csv",
    mimeType: "text/csv",
    buffer: csv(
      "Trading Symbol,Exchange Segment,Transaction Type,Traded Quantity,Traded Price,Exchange Trade ID,Exchange Time",
      "RELIANCE,NSE_EQ,BUY,3,1300.50,E2E-DH-1,2025-04-01 10:15:00",
      "NIFTY-Apr2025-23000-CE,NSE_FNO,BUY,75,10.5,E2E-DH-2,2025-04-01 10:16:00",
    ),
  });
  await page.getByRole("button", { name: "Preview" }).click();
  const matched = page.getByText(/Columns Matched \(\d+ of \d+\) · Dhan trade history/);
  await expect(matched).toBeVisible({ timeout: 15_000 });
  await matched.click();
  await expect(page.getByTestId("map-used")).toContainText("Unconfirmed");
  await expect(page.getByTestId("map-used")).toContainText("detected from the header row");
  await expect(page.getByText("F&O Skipped")).toBeVisible();
  await page.getByRole("button", { name: "Confirm Import (1)" }).click();
  await expect(page.getByText("Imported 1 trade.", { exact: false })).toBeVisible({
    timeout: 15_000,
  });

  // A file no built-in map reads: the preview names the missing columns and
  // opens the mapper, which starts from a guess.
  await file.setInputFiles({
    name: "mine.csv",
    mimeType: "text/csv",
    buffer: csv("When,Ticker,B/S,Units,Rate", "2025-04-02,TCS,Buy,2,3500"),
  });
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(
    page.getByText(/missing required columns for the Dhan trade history map/),
  ).toBeVisible({ timeout: 15_000 });
  const mapper = page.getByTestId("column-mapper");
  await expect(mapper).toBeVisible();
  await expect(mapper.getByLabel("Symbol")).toHaveValue("Ticker");
  await mapper.getByLabel(/^Trade Date/).selectOption("When");
  await mapper.getByLabel("Exchange When the File Has None").selectOption("NSE");
  await mapper.getByLabel("Map Name").fill("My Test Map");
  await mapper.getByRole("button", { name: "Save Map and Preview" }).click();
  const mine = page.getByText(/Columns Matched \(\d+ of \d+\) · My Test Map/);
  await expect(mine).toBeVisible({ timeout: 15_000 });
  await mine.click();
  await expect(page.getByTestId("map-used")).toContainText("Your Map");
  await page.getByRole("button", { name: "Confirm Import (1)" }).click();
  await expect(page.getByText("Imported 1 trade.", { exact: false })).toBeVisible({
    timeout: 15_000,
  });

  await page.reload();
  await expect(page.getByRole("region", { name: "Your column maps" })).toContainText("My Test Map");
  // Scoped to the page body: a second copy can sit in a transient overlay.
  await expect(page.locator("#main").getByText(/· your map/)).toBeVisible();
});

test("a screen's basket downloads as CSV, with no Kite form without KITE_API_KEY", async ({
  page,
}) => {
  await signUp(page, "basket");
  await page.goto("/screener");
  const basket = page.getByTestId("screen-basket");
  await basket.locator("summary").click();
  await basket.getByLabel("Shares of Each").fill("2");
  await expect(basket.getByText(/never places an order/)).toBeVisible();
  await expect(basket.getByRole("button", { name: /Review in Kite/ })).toHaveCount(0);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    basket.getByRole("button", { name: /Download CSV/ }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^stockviz-basket-screen-\d{4}-\d{2}-\d{2}\.csv$/);
  const path = await download.path();
  const text = await readFile(path, "utf8");
  const [header, first] = text.split("\n");
  expect(header).toBe("symbol,exchange,side,quantity,order_type,price,trigger");
  expect(first).toMatch(/^[^,]+,(NSE|BSE|US),BUY,2,MARKET,,$/);
});
