import type { Locator, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

// A6.8 (M2.10): the chart workspace. Signup is capped at 5 per IP an hour and
// the other specs use all five, so this spec signs up from its own address.
// The cap reads the hop our proxy adds to x-forwarded-for
// (`lib/client-address.ts`); with no proxy in front of the test server this
// header plays the proxy. Nothing else here depends on it.
test.describe.configure({ retries: 0 });
test.use({ extraHTTPHeaders: { "x-forwarded-for": "198.51.100.68" } });

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Charts");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

function pane(main: Locator, n: number): Locator {
  return main.getByTestId(`chart-pane-${n}`);
}

async function setSymbol(main: Locator, n: number, symbol: string): Promise<void> {
  const input = main.getByLabel(`Symbol for chart ${n + 1}`);
  await input.fill(symbol);
  await input.press("Enter");
  await expect(pane(main, n)).toHaveAttribute("data-symbol", symbol);
}

test("guests are sent to sign in", async ({ page }) => {
  await page.goto("/charts");
  await expect(page).toHaveURL(/sign-in-required/);
});

test("a saved four-pane layout reloads, and the blue group moves together", async ({ page }) => {
  test.setTimeout(120_000);
  await signUp(page, `e2e+charts+${Date.now()}@example.com`);
  const main = page.locator("#main");

  // A template from the stock page: line chart, log scale, RSI.
  await page.goto("/stocks/AAPL?indicators=rsi_14&type=line&scale=log");
  await main.getByTestId("save-template-toggle").click();
  await main.getByTestId("save-template-name").fill("E2E Oscillators");
  await main.getByTestId("save-template-submit").click();
  await expect(main.getByTestId("save-template-saved")).toContainText("Saved E2E Oscillators");

  // An empty library, one chart to start.
  await page.goto("/charts");
  await expect(main.getByRole("heading", { name: "Charts", exact: true })).toBeVisible();
  await expect(main.getByTestId("layouts-empty")).toHaveText(/No saved layouts yet/);
  await expect(main.getByTestId("chart-pane-0")).toBeVisible();

  // Four panes: AAPL weekly and 15-minute (blue), MSFT with the template
  // (pink), GOOGL monthly (unlinked).
  await main.getByLabel("Grid").selectOption("4");
  await expect(main.locator("[data-grid='4']")).toBeVisible();
  await expect(pane(main, 3)).toBeVisible();
  await setSymbol(main, 0, "AAPL");
  await main.getByLabel("Link colour for chart 1").selectOption("blue");
  await expect(pane(main, 0)).toHaveAttribute("data-link", "blue");
  await main.getByLabel("Interval for chart 1").selectOption("1wk");
  await expect(pane(main, 0)).toHaveAttribute("data-interval", "1wk");
  await main.getByLabel("Link colour for chart 2").selectOption("blue");
  await expect(pane(main, 1)).toHaveAttribute("data-link", "blue");
  await main.getByLabel("Interval for chart 2").selectOption("15m");
  await expect(pane(main, 1)).toHaveAttribute("data-interval", "15m");
  // No minute bars are seeded: the pane says so and draws daily.
  await expect(pane(main, 1).getByTestId("pane-note")).toContainText("showing daily");
  await setSymbol(main, 2, "MSFT");
  await main.getByLabel("Link colour for chart 3").selectOption("pink");
  await expect(pane(main, 2)).toHaveAttribute("data-link", "pink");
  await main.getByLabel("Template for chart 3").selectOption({ label: "E2E Oscillators" });
  await expect(pane(main, 2).getByTestId("pane-look")).toContainText("E2E Oscillators");
  await expect(pane(main, 2).getByTestId("price-chart")).toHaveAttribute(
    "data-panes",
    "price,volume,rsi",
  );
  await setSymbol(main, 3, "GOOGL");
  await main.getByLabel("Interval for chart 4").selectOption("1mo");
  await expect(pane(main, 3)).toHaveAttribute("data-interval", "1mo");

  await main.getByTestId("layout-name").fill("E2E Desk");
  await main.getByTestId("layout-save").click();
  await expect(page).toHaveURL(/layout=\d+/);
  const layoutId = new URL(page.url()).searchParams.get("layout");
  const library = main.getByTestId("saved-layouts");
  await expect(library.getByRole("link", { name: /E2E Desk/ })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // Acceptance: the saved layout alone reloads every pane.
  await page.goto(`/charts?layout=${layoutId}`);
  await page.reload();
  const expected = [
    ["AAPL", "1wk", "blue"],
    ["AAPL", "15m", "blue"],
    ["MSFT", "1d", "pink"],
    ["GOOGL", "1mo", ""],
  ];
  for (const [n, [symbol, interval, link]] of expected.entries()) {
    await expect(pane(main, n)).toHaveAttribute("data-symbol", symbol);
    await expect(pane(main, n)).toHaveAttribute("data-interval", interval);
    await expect(pane(main, n)).toHaveAttribute("data-link", link);
  }
  const templateId = await pane(main, 2).getAttribute("data-template");
  expect(templateId).toMatch(/^\d+$/);
  for (const n of [0, 1, 3]) await expect(pane(main, n)).toHaveAttribute("data-template", "");
  await expect(main.getByLabel("Template for chart 3")).toHaveValue(templateId ?? "");
  await expect(pane(main, 2).getByTestId("pane-look")).toContainText("E2E Oscillators");

  // Acceptance: a new symbol in the blue group moves every blue pane, nothing else.
  await setSymbol(main, 1, "NVDA");
  await expect(pane(main, 0)).toHaveAttribute("data-symbol", "NVDA");
  await expect(pane(main, 2)).toHaveAttribute("data-symbol", "MSFT");
  await expect(pane(main, 3)).toHaveAttribute("data-symbol", "GOOGL");
  await expect(pane(main, 0)).toHaveAttribute("data-interval", "1wk");
  await expect(pane(main, 1)).toHaveAttribute("data-interval", "15m");

  // A symbol StockViz doesn't have: that pane says so; the rest still draw.
  await setSymbol(main, 3, "NOPE");
  await expect(pane(main, 3).getByTestId("pane-missing")).toContainText("NOPE");
  await expect(pane(main, 2).getByTestId("price-chart")).toBeVisible();

  // On a phone the grid is tabs.
  await page.setViewportSize({ width: 390, height: 844 });
  const tabs = main.getByRole("tablist", { name: "Charts" });
  await expect(tabs).toBeVisible();
  await expect(pane(main, 0)).toBeVisible();
  await expect(pane(main, 2)).toBeHidden();
  await tabs.getByRole("tab").nth(2).click();
  await expect(pane(main, 2)).toBeVisible();
  await expect(pane(main, 0)).toBeHidden();
});
