import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

test("journal calendar, drill-down, history, and mobile sheet", async ({ page }, testInfo) => {
  test.skip(
    !process.env.JOURNAL_TEST_DATABASE_URL,
    "Requires disposable journal verification database",
  );
  test.setTimeout(120_000);
  const email = `journal-browser-${Date.now()}@example.com`;
  await page.goto("/signup");
  await page.getByLabel("Name").fill("Journal Verification");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("journal-test-password-1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
  execFileSync(
    process.env.JOURNAL_TEST_PYTHON ??
      resolve(
        process.platform === "win32"
          ? "../api/.venv/Scripts/python.exe"
          : "../api/.venv/bin/python",
      ),
    ["tests/e2e/journal-seed.py", email],
    { env: process.env },
  );
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/portfolio?tab=journal&month=2026-07");
  await expect(page.getByRole("tab", { name: "Journal" })).toHaveAttribute("aria-selected", "true");
  const journal = page.getByRole("region", { name: "Trading journal", exact: true });
  await expect(journal.getByText("+$880.00", { exact: true })).toBeVisible();
  await journal.screenshot({ path: testInfo.outputPath("profitable-month.png") });
  await page.getByRole("button", { name: "Next month" }).click();
  await expect(journal.getByText("+$622.00", { exact: true })).toBeVisible();
  await journal.screenshot({ path: testInfo.outputPath("mixed-month.png") });
  await page.getByTestId("journal-day-2026-08-19").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "August 19, 2026" })).toBeVisible();
  await expect(dialog.getByText("Average cost")).toBeVisible();
  await page.waitForTimeout(250);
  await page.screenshot({ path: testInfo.outputPath("day-inspector.png") });
  await page.getByTestId("journal-day-2026-08-20").click();
  await expect(dialog.getByRole("heading", { name: "August 20, 2026" })).toBeVisible();
  await expect(dialog.getByText("−$120.00").first()).toBeVisible();
  await page.goBack();
  await expect(dialog.getByRole("heading", { name: "August 19, 2026" })).toBeVisible();
  await page.reload();
  await expect(dialog.getByText("Average cost")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await page.getByTestId("journal-week-2026-08-17").click();
  await expect(dialog.getByText("Best trade")).toBeVisible();
  await expect(dialog.getByText("Worst trade")).toBeVisible();
  await page.waitForTimeout(250);
  await page.screenshot({ path: testInfo.outputPath("week-inspector.png") });
  await page.keyboard.press("Escape");
  await page.getByLabel("Month", { exact: true }).selectOption("6");
  await expect(page.getByText("No closed trades this month.")).toBeVisible();
  await journal.screenshot({ path: testInfo.outputPath("empty-month.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/portfolio?tab=journal&month=2026-08");
  await journal.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  await page.screenshot({ path: testInfo.outputPath("mobile-calendar.png") });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.getByTestId("journal-day-2026-08-19").click();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(dialog.getByText("Average cost")).toBeVisible();
  await page.waitForTimeout(250);
  await page.screenshot({ path: testInfo.outputPath("mobile-sheet.png") });
  await page.getByRole("button", { name: "Close journal detail" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByTestId("journal-day-2026-08-19")).toBeFocused();
  await page.setViewportSize({ width: 320, height: 740 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
});
