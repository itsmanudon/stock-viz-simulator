import { expect, test } from "@playwright/test";

test("guest research routes use the product shell without a website footer", async ({ page }) => {
  await page.goto("/markets");

  await expect(page.getByRole("navigation", { name: "Product" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Search tickers, pages and actions" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Overview" }).first()).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("contentinfo")).toHaveCount(0);
});

test("public pages keep concise website chrome", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "Public" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
  // No product sidebar. The footer has its own "Product" column of links to
  // the product pages, so look outside the footer.
  await expect(page.locator('nav[aria-label="Product"]:not(footer nav)')).toHaveCount(0);
});

test("mobile product navigation exposes the same hierarchy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/screener");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Product navigation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Screener" })).toBeVisible();
  // Workspaces other than Today and the current one start folded.
  await drawer.getByRole("button", { name: "Workbench" }).click();
  await expect(drawer.getByRole("link", { name: "Compare" })).toBeVisible();
});

test("each page names itself in the browser tab (audit A1)", async ({ page }) => {
  for (const [path, title] of [
    ["/", "StockViz | Market Visualization Platform"],
    ["/markets", "Markets | StockViz"],
    ["/screener", "Screener | StockViz"],
    ["/checklist", "Checklist | StockViz"],
    ["/stocks/aapl", "AAPL | StockViz"],
    ["/login", "Sign in | StockViz"],
  ] as const) {
    await page.goto(path);
    await expect(page).toHaveTitle(title);
  }
});

test("the six workspaces light up for their routes (A3.6)", async ({ page }) => {
  const product = page.getByRole("navigation", { name: "Product" });
  for (const [path, workspace] of [
    ["/markets", "Markets"],
    ["/stocks/AAPL", "Workbench"],
    ["/backtest", "Quant Lab"],
    ["/copilot", "AI Copilot"],
  ] as const) {
    await page.goto(path);
    await expect(product.getByRole("group", { name: workspace })).toHaveAttribute(
      "data-active",
      "true",
    );
    await expect(product.locator('[role="group"][data-active="true"]')).toHaveCount(1);
  }
  // A8.5: signed out, the copilot asks for a sign-in and offers nothing else.
  await expect(page.getByTestId("copilot-signed-out")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sign In to Ask" })).toBeVisible();
});

test("the command palette opens with the keyboard and jumps to a symbol (A3.6)", async ({
  page,
}) => {
  await page.goto("/markets");
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  const input = palette.getByRole("combobox", { name: "Search tickers, pages and actions" });
  await expect(input).toBeFocused();

  await input.fill("AAPL");
  const symbols = palette.getByRole("group", { name: "Symbols" });
  await expect(symbols.getByRole("option").first()).toContainText("AAPL");
  // Pages and actions come first; walk down to the first symbol and open it.
  const before = await palette.getByRole("group", { name: "Pages and Actions" }).count();
  if (before > 0) {
    const count = await palette
      .getByRole("group", { name: "Pages and Actions" })
      .getByRole("option")
      .count();
    for (let i = 0; i < count; i++) await page.keyboard.press("ArrowDown");
  }
  await expect(symbols.getByRole("option").first()).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/stocks\/AAPL$/);
  await expect(
    page.getByRole("navigation", { name: "Product" }).getByRole("group", { name: "Workbench" }),
  ).toHaveAttribute("data-active", "true");
});

test("the command palette jumps to a page and closes with Escape (A3.6)", async ({ page }) => {
  await page.goto("/markets");
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Search tickers, pages and actions" }),
  ).toBeFocused();

  await page.keyboard.press("ControlOrMeta+k");
  await palette.getByRole("combobox").fill("new backtest");
  await expect(palette.getByRole("option").first()).toContainText("New backtest");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/backtest$/);
  await expect(
    page.getByRole("navigation", { name: "Product" }).getByRole("group", { name: "Quant Lab" }),
  ).toHaveAttribute("data-active", "true");
});

test("on a phone the top bar button opens the palette (A3.6)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/screener");
  await page.getByRole("button", { name: "Search tickers, pages and actions" }).click();
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await palette.getByRole("combobox").fill("checklist");
  await palette
    .getByRole("option", { name: /Checklist/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/checklist$/);
});
