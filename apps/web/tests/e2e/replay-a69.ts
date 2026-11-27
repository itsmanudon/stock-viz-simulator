import { type Page, expect } from "@playwright/test";

/**
 * A6.9 (M9.4), run by `trade.spec.ts` on its signed-in page (credential
 * signup is capped at 5 an IP an hour, so this does not sign up again): a
 * replay under the `intrabar_ohlc` profile, a bracket shown as a linked
 * group, and autoplay at 10 bars a second that never double-advances: after
 * playing, the page's bar count is exactly one more than the steps the
 * player made (each step moved one bar, none moved two). Runs on the
 * repository's seeded daily bars (`cli seed` + `backfill`).
 */
export async function replayFullOrders(page: Page): Promise<void> {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/replay?ticker=MSFT");
  await expect(page.getByText(/Stored daily bars for MSFT/)).toBeVisible();
  await page.getByTestId("replay-launch-profile").selectOption("intrabar_ohlc");
  await expect(page.getByTestId("replay-launch-profile-name")).toHaveText("intrabar_ohlc v1");
  await page.getByRole("button", { name: "Start replay" }).click();
  await page.waitForURL(/\/replay\/\d+/);

  await expect(page.getByTestId("replay-profile")).toHaveText("Fill model · intrabar_ohlc v1");
  // Scoped to #main: `next start` can briefly hold two page trees (apps/web/CLAUDE.md, E2E).
  await expect(page.locator("#main").getByTestId("replay-bar-count")).toHaveText("Bar 1");

  const ticket = page.getByRole("complementary", { name: /Replay ticket/ });
  await ticket.getByTestId("replay-order-type").selectOption("bracket");
  await expect(ticket.getByTestId("replay-bracket-stop")).toBeVisible();
  await expect(ticket.getByTestId("replay-bracket-target")).toBeVisible();
  await ticket.getByRole("button", { name: "Place bracket buy" }).click();
  await expect(ticket.getByTestId("replay-order-placed")).toContainText("Placed bracket buy");
  const group = page.getByTestId("replay-bracket");
  await expect(group).toBeVisible();
  await expect(group.getByTestId("replay-bracket-leg")).toHaveCount(2);
  await expect(group.locator('[data-leg="stop_loss"]')).toHaveAttribute("data-status", "open");

  const player = page.getByTestId("replay-autoplay");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("4");
  await expect(player).toHaveAttribute("data-speed", "10");
  await page.keyboard.press("Space");
  await expect(player).toHaveAttribute("data-playing", "true");
  await page.waitForTimeout(2500);
  await page.keyboard.press("Space");
  await expect(player).toHaveAttribute("data-playing", "false");
  // Once the last step and refresh land, the bars shown are the start bar
  // plus one per step: no step moved two bars.
  const barCount = page.locator("#main").getByTestId("replay-bar-count");
  await expect
    .poll(
      async () => {
        const steps = Number(await player.getAttribute("data-advances"));
        return (await barCount.textContent()) === `Bar ${steps + 1}` ? steps : -1;
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThanOrEqual(3);
  const advances = Number(await player.getAttribute("data-advances"));
  await page.reload();
  await expect(barCount).toHaveText(`Bar ${advances + 1}`);
}
