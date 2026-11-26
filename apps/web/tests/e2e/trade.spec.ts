import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { replayFullOrders } from "./replay-a69";

// Signup is capped at 5/IP/hour. A retry would consume a sixth attempt and
// mask the original locator error behind a rate-limit timeout.
test.describe.configure({ retries: 0 });

async function signUp(page: Page, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/");
}

// One signup covers the operational loop and Replay Lab. Credential signup is
// capped at 5/IP/hour, and auth + portfolio + stock-workspace consume the other slots.
test("operational trading loop from ticket to orders, watchlist, alerts, and replay", async ({
  page,
}) => {
  test.setTimeout(180_000); // A6.9's replay flow runs at the end
  const email = `e2e+ops+${Date.now()}@example.com`;
  await signUp(page, email);
  const main = page.locator("#main");

  await page.goto("/trade?ticker=AAPL");
  await expect(main.getByRole("heading", { name: "Trade", exact: true })).toBeVisible();
  await expect(main.getByLabel("Symbol")).toHaveValue("AAPL");
  await expect(
    main
      .getByRole("region", { name: "Order ticket" })
      .getByText(/Submits immediately at the latest stored daily close/i),
  ).toBeVisible();
  await expect(
    main.getByRole("region", { name: "Account" }).getByText("Buying power"),
  ).toBeVisible();

  await main.getByLabel("Quantity").fill("1");
  // The ticket reviews before it places (UX-4): open the review, then place.
  await main.getByRole("button", { name: /Review market buy/i }).click();
  await main.getByRole("button", { name: /Place market buy/i }).click();
  await expect(main.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    "Filled Buy",
    { timeout: 10_000 },
  );
  await expect(main.getByRole("table", { name: "Recent paper fills" })).toContainText("AAPL");

  // Phase 9.1 (UX-5): the option ticket quotes with its rate and Greeks.
  // Indexes are not offered as underlyings: the API refuses options on them.
  // The single-contract ticket's select (the strategy builder has its own).
  const ticketUnderlying = main.locator("#opt-ticker");
  await expect(ticketUnderlying.locator('option[value="^GSPC"]')).toHaveCount(0);
  await ticketUnderlying.selectOption("AAPL");
  const optionQuote = main.getByRole("region", { name: "Option quote" });
  await expect(optionQuote).toContainText("Risk-free rate", { timeout: 10_000 });
  await expect(optionQuote).toContainText(/closes/);
  await expect(main.getByLabel("Greeks")).toContainText("Delta");
  await expect(main.getByLabel("Greeks")).toContainText("Rho");

  // Phase 9.2: write a cash-secured put; its strike value is held back.
  await main.getByRole("button", { name: "Write covered" }).click();
  await main.getByRole("button", { name: "Put", exact: true }).click();
  await expect(optionQuote).toContainText("Cash held back", { timeout: 10_000 });
  await main.getByRole("button", { name: /Write cash-secured put, receive/ }).click();
  await expect(main.getByText(/Wrote 1 AAPL Put .* and received/)).toBeVisible({ timeout: 10_000 });
  // Phase 9.5: open a bull call spread from the builder, reviewed first.
  await page.goto("/trade?ticker=AAPL");
  const builder = main.getByRole("region", { name: "Strategy builder" });
  await builder.getByLabel("Underlying").selectOption("AAPL");
  await expect(builder.getByRole("region", { name: "Strategy figures" })).toContainText(
    "Most it can lose",
    { timeout: 15_000 },
  );
  await builder.getByRole("button", { name: "Review strategy" }).click();
  await builder.getByRole("button", { name: "Place bull call spread" }).click();
  await expect(builder.getByText(/Opened a bull call spread on AAPL/)).toBeVisible({
    timeout: 10_000,
  });

  await page.goto("/portfolio?tab=options");
  await expect(
    main.getByRole("table", { name: "Options positions" }).getByText("Cash-secured put (written)"),
  ).toBeVisible();
  await expect(main.getByRole("region", { name: "Strategies" })).toContainText("Bull call spread");
  await expect(main.getByRole("region", { name: "Expirations" })).toContainText(
    /Settles in cash|Expires|Assigned/,
  );
  await expect(main.getByRole("region", { name: "Options Greeks" })).toContainText("Dollar delta");

  await page.goto("/trades");
  await expect(main.getByRole("heading", { name: "Trade history" })).toBeVisible();
  await expect(main.locator("tbody tr").first()).toContainText(/buy/i);

  await page.goto("/orders");
  await expect(main.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  await expect(main.getByRole("heading", { name: "No pending orders" })).toBeVisible();
  await expect(
    main.getByRole("navigation", { name: "Order status" }).getByRole("link", { name: "Filled" }),
  ).toHaveAttribute("href", "/orders?status=filled");

  await page.goto("/watchlist");
  await expect(main.getByRole("heading", { name: "Watchlist", exact: true })).toBeVisible();
  // UX-7 (Phase 6.6): a search box with suggestions, not a select.
  await main.getByLabel("Add symbol").fill("AAPL");
  await main.getByRole("button", { name: "Add to watchlist" }).click();
  await expect(main.getByRole("link", { name: "AAPL" }).first()).toHaveAttribute(
    "href",
    "/stocks/AAPL",
  );

  await page.goto("/alerts?ticker=AAPL");
  await expect(main.getByRole("heading", { name: "Alerts", exact: true })).toBeVisible();
  // Phase 7.3: rules of several kinds, judged after the nightly run.
  await expect(main.locator("header")).toContainText(/not real-time monitoring/i);

  const create = main.getByRole("region", { name: "Create alert" });
  await create.getByLabel("Target (USD)").fill("1");
  await create.getByRole("button", { name: "Create alert" }).click();
  await expect(main.getByRole("list", { name: "Alert rules" })).toContainText("AAPL", {
    timeout: 10_000,
  });
  await expect(create.getByText("Alert set.")).toBeVisible();

  const leaked: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/v1/symbols/")) leaked.push(url);
    if (url.includes("/v1/quotes")) leaked.push(url);
    if (url.includes("/v1/news")) leaked.push(url);
  });

  await page.goto("/replay");
  await expect(main.getByRole("heading", { name: "Replay", exact: true })).toBeVisible();
  await expect(main.getByText("legacy_close v1", { exact: true })).toBeVisible();
  await main.getByLabel("Symbol").selectOption("AAPL");
  await expect(main.getByText(/Stored daily bars for AAPL/i)).toBeVisible({ timeout: 10_000 });
  await main.getByLabel("Start date").fill("2020-01-06");
  await main.getByLabel("End date").fill("2020-01-17");
  await main.getByRole("button", { name: "Start replay" }).click();
  await expect(page).toHaveURL(/\/replay\/\d+/, { timeout: 15_000 });
  await expect(main.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
  await expect(main.getByText(/stored daily bars 2020-01-06 → 2020-01-17/)).toBeVisible();
  // A real session: the old seed data put bars on weekends (UI audit T6).
  await expect(main.getByText(/Monday, January 6, 2020/)).toBeVisible();
  await expect(main.getByRole("region", { name: /replay price chart/i })).toBeVisible();
  await expect(
    main.getByRole("region", { name: /replay price chart/i }).getByText("Replay close"),
  ).toBeVisible();
  await expect(main.getByText(/Indicative/i)).toHaveCount(0);

  const desktopTicket = main.locator("aside").getByRole("button", { name: /Submit market buy/i });
  if (await desktopTicket.isVisible()) {
    await desktopTicket.click();
  } else {
    await main.getByRole("button", { name: /Buy AAPL in replay/i }).click();
    await main.getByRole("button", { name: /Submit market buy/i }).click();
  }
  await expect(main.getByText(/Filled BUY/i)).toBeVisible({ timeout: 10_000 });
  await expect(main.getByRole("table", { name: "Replay fills" })).toContainText("AAPL");
  await expect(main.getByRole("heading", { name: "No open replay position." })).toHaveCount(0);

  const before = await main
    .getByRole("heading", { name: "AAPL", exact: true })
    .locator("..")
    .textContent();
  await main.getByRole("button", { name: "Advance to next session" }).click();
  await expect(main.getByText(/Advanced:/i)).toBeVisible({ timeout: 10_000 });
  const after = await main
    .getByRole("heading", { name: "AAPL", exact: true })
    .locator("..")
    .textContent();
  expect(after).not.toEqual(before);

  await main
    .getByRole("navigation", { name: "Replay workspace" })
    .getByRole("link", { name: "Forensics" })
    .click();
  await expect(main.getByRole("heading", { name: "Trade forensics" })).toBeVisible();
  await expect(main.getByText("So far", { exact: true })).toBeVisible();
  await expect(main.getByRole("table", { name: "Replay episodes" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Decision journal" })).toBeVisible();
  expect(leaked).toEqual([]);

  // A5.2: a second book. Create it in Settings, switch to it in the top bar,
  // trade in it, see the first book unchanged, then view All books.
  await page.goto("/settings#books");
  const newBook = main.getByRole("form", { name: "New book" });
  await newBook.getByLabel("Name").fill("E2E second");
  await newBook.getByRole("button", { name: "Create book" }).click();
  await expect(newBook.getByText("Created E2E second (USD).")).toBeVisible({ timeout: 10_000 });

  await page.goto("/trade?ticker=MSFT");
  const switcher = page.getByRole("button", { name: /Switch book/ });
  await switcher.click();
  await page
    .getByRole("list", { name: "Books" })
    .getByRole("link", { name: /E2E second/ })
    .click();
  await page.waitForURL(/[?&]book=\d+/);
  await expect(switcher).toHaveAccessibleName(/Book: E2E second/);
  await expect(
    main.getByRole("region", { name: "Order ticket" }).getByTestId("ticket-book"),
  ).toContainText("Trades into E2E second");
  await expect(main.getByLabel("Symbol")).toHaveValue("MSFT");
  await main.getByLabel("Quantity").fill("2");
  await main.getByRole("button", { name: /Review market buy/i }).click();
  await main.getByRole("button", { name: /Place market buy/i }).click();
  await expect(main.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    /Filled Buy 2(\.0+)? MSFT/,
    { timeout: 10_000 },
  );

  // A5.4: plan the next MSFT buy on the ticket. The review shows the plan's
  // risk and R:R, and the plan locks at the fill.
  await main.getByRole("button", { name: "New order" }).click();
  await main.getByLabel("Quantity").fill("3");
  await main.getByRole("checkbox", { name: /Plan this trade/ }).check();
  const ticketPlan = main.getByTestId("ticket-plan");
  await expect(ticketPlan.getByLabel("Size (shares)")).toHaveValue("3");
  const plannedEntry = Number(await ticketPlan.getByLabel("Planned entry").inputValue());
  expect(plannedEntry).toBeGreaterThan(5);
  await ticketPlan.getByLabel("Stop", { exact: true }).fill((plannedEntry - 5).toFixed(2));
  await ticketPlan.getByLabel("Target (optional)").fill((plannedEntry + 15).toFixed(2));
  await ticketPlan.getByLabel("Tags").fill("e2e");
  await main.getByRole("button", { name: /Review market buy/i }).click();
  const reviewPlan = main.getByTestId("review-plan");
  await expect(reviewPlan).toContainText("Risk if stopped");
  await expect(reviewPlan).toContainText("3.00 : 1");
  await main.getByRole("button", { name: /Place market buy/i }).click();
  await expect(main.getByRole("region", { name: "Order ticket" }).locator("output")).toContainText(
    /Filled Buy 3(\.0+)? MSFT/,
    { timeout: 10_000 },
  );
  const secondBook = new URL(page.url()).searchParams.get("book");
  await page.goto(`/portfolio?tab=journal&book=${secondBook}`);
  const lockedPlan = main.getByTestId("plan-row").first();
  await expect(lockedPlan).toContainText("MSFT");
  await expect(lockedPlan.getByTestId("plan-badge")).toHaveText("Locked");
  await page.goto(`/trade?ticker=MSFT&book=${secondBook}`);

  // The default book still holds only its own fills.
  await switcher.click();
  await page
    .getByRole("list", { name: "Books" })
    .getByRole("link", { name: /^Default/ })
    .click();
  await expect(switcher).toHaveAccessibleName(/Book: Default/);
  await page.goto(page.url().replace("/trade?", "/trades?"));
  await expect(main.getByRole("table")).toContainText("AAPL");
  await expect(main.getByRole("table")).not.toContainText("MSFT");

  // A5.4: the default book's AAPL was bought without a plan. A plan written
  // for it now is labelled "written after entry", never locked.
  const defaultTrades = page.url();
  await page.goto(defaultTrades.replace("/trades?", "/portfolio?tab=journal&"));
  const lateForm = main.getByTestId("plan-open-position");
  await lateForm.locator("summary").click();
  await lateForm.getByLabel("Position").selectOption("AAPL");
  const lateEntry = Number(await lateForm.getByLabel("Entry").inputValue());
  await lateForm.getByLabel("Stop", { exact: true }).fill((lateEntry - 5).toFixed(2));
  await lateForm.getByRole("button", { name: "Save plan" }).click();
  // The holding has a plan now, so the form leaves and the row arrives.
  const latePlan = main.getByTestId("plan-row").filter({ hasText: "AAPL" });
  await expect(latePlan.getByTestId("plan-badge")).toHaveText("Written after entry", {
    timeout: 10_000,
  });
  await page.goto(defaultTrades);

  // All books: both fills, each naming its book, and the combined portfolio.
  await switcher.click();
  await page
    .getByRole("list", { name: "Books" })
    .getByRole("link", { name: /All books/ })
    .click();
  await page.waitForURL(/[?&]book=all/);
  await expect(switcher).toHaveAccessibleName(/Book: All books/);
  await expect(main.getByRole("table")).toContainText("MSFT");
  await expect(main.getByRole("table")).toContainText("AAPL");
  await expect(main.getByRole("table")).toContainText("E2E second");
  await page.goto("/portfolio?book=all");
  await expect(main.getByRole("heading", { name: /All books · 2 books in USD/ })).toBeVisible();
  // The ticket takes no orders in All books, and says why.
  await page.goto("/trade?ticker=AAPL&book=all");
  await expect(main.getByTestId("ticket-blocked").first()).toContainText("read-only");
  await expect(main.getByRole("button", { name: /Review market buy/i })).toBeDisabled();

  // On a phone, Orders, Watchlist and Alerts lay out as cards instead of a
  // table that scrolls the page sideways (UI audit P1). This account has a
  // watched symbol and an alert; its market buy filled at once, so Orders
  // (conditional orders only) shows its empty state, which must fit too. The
  // order card itself is covered in tests/unit/order-card.test.tsx.
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [path, list] of [
    ["/orders?status=all", null],
    ["/watchlist", "Watched securities"],
    ["/alerts?view=all", "Alert rules"],
  ] as const) {
    await page.goto(path);
    if (list) await expect(main.getByRole("list", { name: list })).toContainText("AAPL");
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflows, `${path} scrolls sideways at 390px`).toBe(false);
  }

  // A6.9: brackets, the named profile and 10x autoplay on the same account.
  await replayFullOrders(page);
});
