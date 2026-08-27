# StockViz Phase 3 Portfolio Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a performance-first authenticated Portfolio workspace with accurate multi-currency semantics, operational tabs, high-quality holdings views, exposure insights, and intentional mobile behavior.

**Architecture:** Keep the route page as the single server orchestrator and pass already-fetched portfolio, history, analytics, orders, and dividend data into focused presentational components. Put pure financial/view-state derivations in a tested module; limit client code to the lightweight-charts equity curve and Radix tab URL synchronization.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 6, Tailwind CSS 4, Radix UI, lightweight-charts, Vitest/Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-27-stockviz-phase3-portfolio-workspace-design.md`

## Global Constraints

- Start from exact Phase 2 commit `86792b6d3ebe7056f6f1aafcff0948b8d6cec8ed` on `redesign/ui-phase3-portfolio-workspace`.
- Preserve the Phase 1 application shell, Phase 2 stock workspace, existing routes, authentication, APIs, and trading behavior.
- Keep total/current portfolio values in `portfolio.display_currency`; label historical NAV change as USD NAV.
- Label sector allocation as equity-only and movers as movers, never formal attribution.
- Do not infer currency for pending-order trigger prices; label them as native quote values.
- Do not perform new client-side FX conversion or add realtime, benchmarking, Greeks, tax-lot, optimization, or brokerage concepts.
- Use existing Tailwind/shadcn/Radix/lightweight-charts dependencies; add no chart or UI dependency.
- Keep server components as the default and follow strict red-green-refactor for behavior changes.
- Keep standalone `/orders`, `/trade`, and `/stocks/[ticker]` stable.
- Do not change API migrations or weaken behavior to work around database drift.

---

### Task 1: Portfolio view-model and financial semantics

**Files:**
- Create: `apps/web/lib/portfolio-view-model.ts`
- Create: `apps/web/tests/unit/portfolio-view-model.test.ts`

**Interfaces:**
- Consumes: `PortfolioHistoryPoint`, `Position`, and `ProjectedDividend` from `@/lib/api/trading`.
- Produces: `PortfolioRange`, `PortfolioTab`, `PORTFOLIO_RANGES`, `parsePortfolioRange(raw)`, `parsePortfolioTab(raw)`, `portfolioRangeDays(range)`, `calculateNavChange(points)`, `calculatePortfolioWeight(positionValue, totalValue)`, `currencyForProjectedDividend(ticker, positions)`, `formatCurrency(raw, currency)`, `formatQuantity(raw)`, `formatSignedPercent(value)`, and `buildPortfolioHref({ range, tab })`.

- [ ] **Step 1: Write failing tests for range parsing and href preservation**

```ts
expect(parsePortfolioRange(undefined)).toBe("3m");
expect(parsePortfolioRange("1y")).toBe("1y");
expect(parsePortfolioRange("bad")).toBe("3m");
expect(parsePortfolioTab("orders")).toBe("orders");
expect(parsePortfolioTab("bad")).toBe("positions");
expect(portfolioRangeDays("all")).toBeNull();
expect(buildPortfolioHref({ range: "1y", tab: "orders" })).toBe(
  "/portfolio?range=1y&tab=orders",
);
```

- [ ] **Step 2: Run the view-model tests and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-view-model.test.ts`

Expected: FAIL because `@/lib/portfolio-view-model` does not exist.

- [ ] **Step 3: Add the minimal range and URL implementation**

```ts
export const PORTFOLIO_RANGES = [
  { value: "1m", label: "1M", days: 30 },
  { value: "3m", label: "3M", days: 90 },
  { value: "1y", label: "1Y", days: 365 },
  { value: "all", label: "All", days: null },
] as const;

export type PortfolioRange = (typeof PORTFOLIO_RANGES)[number]["value"];
export type PortfolioTab = "positions" | "options" | "orders" | "income";
```

- [ ] **Step 4: Add failing tests for NAV, weight, currency joins, and formatting**

```ts
expect(calculateNavChange([
  { date: "2026-06-01", nav: "100000" },
  { date: "2026-08-27", nav: "112500" },
])).toEqual({ absolute: 12500, percent: 12.5, firstDate: "2026-06-01", lastDate: "2026-08-27" });
expect(calculateNavChange([{ date: "2026-08-27", nav: "100000" }])).toBeNull();
expect(calculatePortfolioWeight("250", "1000")).toBe(25);
expect(calculatePortfolioWeight("250", "0")).toBeNull();
expect(currencyForProjectedDividend("7203.T", positions)).toBe("JPY");
expect(currencyForProjectedDividend("UNKNOWN", positions)).toBeNull();
```

- [ ] **Step 5: Run the tests and confirm the new assertions fail**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-view-model.test.ts`

Expected: FAIL on missing calculation/formatting exports.

- [ ] **Step 6: Implement safe pure calculations and shared formatting**

Implement finite-number guards, zero-denominator handling, ISO-4217 fallback formatting, six-decimal quantity trimming, explicit signs, and a ticker-to-position native-currency lookup. Do not calculate FX.

- [ ] **Step 7: Run the focused tests and all existing unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-view-model.test.ts`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass.

- [ ] **Step 8: Commit the financial view-model**

```powershell
git add -- apps/web/lib/portfolio-view-model.ts apps/web/tests/unit/portfolio-view-model.test.ts
git commit -m "feat(web): add portfolio view model"
```

---

### Task 2: URL-backed accessible portfolio tabs

**Files:**
- Create: `apps/web/components/portfolio-tabs.tsx`
- Create: `apps/web/tests/unit/portfolio-tabs.test.tsx`

**Interfaces:**
- Consumes: `PortfolioTab`, `PortfolioRange`, `buildPortfolioHref` from Task 1 plus four `ReactNode` panels and optional counts.
- Produces: `PortfolioTabs({ activeTab, range, positions, options, orders, income, optionCount, orderCount })`.

- [ ] **Step 1: Write the failing tab semantics test**

```tsx
render(
  <PortfolioTabs
    activeTab="positions"
    range="3m"
    positions={<p>Positions panel</p>}
    options={<p>Options panel</p>}
    orders={<p>Orders panel</p>}
    income={<p>Income panel</p>}
    optionCount={2}
    orderCount={1}
  />,
);
expect(screen.getByRole("tab", { name: "Positions" })).toHaveAttribute("aria-selected", "true");
expect(screen.getByRole("tab", { name: "Options 2" })).toBeVisible();
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-tabs.test.tsx`

Expected: FAIL because `PortfolioTabs` does not exist.

- [ ] **Step 3: Implement the minimal Radix tab shell**

Use `Tabs` from `radix-ui`, controlled with `activeTab`. On `onValueChange`, call `router.push(buildPortfolioHref({ range, tab: value }))`. Render a horizontally scrollable `Tabs.List` with a gold ledger marker for the selected trigger and focus-visible ring styles.

- [ ] **Step 4: Add a failing URL-state test**

Mock `next/navigation` with `useRouter().push`, click `Orders 1`, and assert `push("/portfolio?range=3m&tab=orders")`. Add a keyboard assertion that ArrowRight moves tab focus/selection through Radix behavior.

- [ ] **Step 5: Run the test to verify the URL assertion fails before completing navigation**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-tabs.test.tsx`

Expected: FAIL until `onValueChange` pushes the preserved range and selected tab.

- [ ] **Step 6: Complete URL synchronization and panel focus styling**

Ensure each `Tabs.Content` has a stable value, meaningful outline, and no child fetch. Keep invalid-tab fallback on the server helper.

- [ ] **Step 7: Run focused and full unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-tabs.test.tsx`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass.

- [ ] **Step 8: Commit portfolio tabs**

```powershell
git add -- apps/web/components/portfolio-tabs.tsx apps/web/tests/unit/portfolio-tabs.test.tsx
git commit -m "feat(web): add portfolio content navigation"
```

---

### Task 3: Performance ledger, range controls, and metrics strip

**Files:**
- Create: `apps/web/components/portfolio-performance.tsx`
- Create: `apps/web/components/portfolio-metrics.tsx`
- Modify: `apps/web/components/equity-curve.tsx`
- Create: `apps/web/tests/unit/portfolio-performance.test.tsx`

**Interfaces:**
- Consumes: `Portfolio`, nullable `PortfolioAnalytics`, `PortfolioHistoryPoint[] | null`, selected `PortfolioRange`/`PortfolioTab`, and Task 1 format/calculation helpers.
- Produces: `PortfolioPerformance({ portfolio, history, range, tab })`, `PortfolioMetrics({ portfolio, analytics })`, and `EquityCurve({ points, accessibleLabel })`.

- [ ] **Step 1: Write failing tests for the dominant value and USD NAV semantics**

```tsx
render(<PortfolioPerformance portfolio={eurPortfolio} history={history} range="3m" tab="positions" />);
expect(screen.getByRole("heading", { name: "Portfolio" })).toBeVisible();
expect(screen.getByText("€128,420.38")).toBeVisible();
expect(screen.getByText("3M USD NAV change")).toBeVisible();
expect(screen.getByText("+$2,184.20")).toBeVisible();
expect(screen.getByText("Latest EOD valuation", { exact: false })).toBeVisible();
```

- [ ] **Step 2: Run the performance test and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-performance.test.tsx`

Expected: FAIL because the new performance components do not exist.

- [ ] **Step 3: Implement the performance ledger without the chart internals change**

Render the dominant display-currency value, signed selected-range USD NAV change, latest snapshot date, Trade link, and `1M / 3M / 1Y / All` links that preserve the active tab. Render history-unavailable and insufficient-history copy distinctly.

- [ ] **Step 4: Add failing tests for compact metric scope and new-portfolio suppression**

```tsx
render(<PortfolioMetrics portfolio={portfolio} analytics={analytics} />);
expect(screen.getByText("Available cash")).toBeVisible();
expect(screen.getByText("Invested equities")).toBeVisible();
expect(screen.getByText("All-history return")).toBeVisible();
expect(screen.getByText(/Based on 240 daily snapshots/)).toBeVisible();

render(<PortfolioMetrics portfolio={emptyPortfolio} analytics={emptyAnalytics} />);
expect(screen.queryByText("Sharpe ratio")).not.toBeInTheDocument();
```

- [ ] **Step 5: Run the tests and confirm the metric assertions fail**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-performance.test.tsx`

Expected: FAIL until the metrics strip exists and suppresses meaningless analytics.

- [ ] **Step 6: Implement the metrics ledger and accessible equity curve**

Use border separators rather than Cards. Add `role="img"` and an accessible label/description around the canvas container. Use `useTheme().resolvedTheme` to select coherent light/dark grid, axis, line, and area colors, recreating the chart only when data or resolved theme changes. Keep the chart height responsive (`h-[240px] sm:h-[300px] lg:h-[340px]`).

- [ ] **Step 7: Run focused and full unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-performance.test.tsx`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass with no jsdom chart errors; mock lightweight-charts only at the canvas boundary if required.

- [ ] **Step 8: Commit the performance ledger**

```powershell
git add -- apps/web/components/portfolio-performance.tsx apps/web/components/portfolio-metrics.tsx apps/web/components/equity-curve.tsx apps/web/tests/unit/portfolio-performance.test.tsx
git commit -m "feat(web): make portfolio performance primary"
```

---

### Task 4: Responsive stock positions and new-portfolio state

**Files:**
- Create: `apps/web/components/portfolio-positions.tsx`
- Create: `apps/web/components/portfolio-empty-state.tsx`
- Create: `apps/web/tests/unit/portfolio-positions.test.tsx`

**Interfaces:**
- Consumes: `Position[]`, display currency, total portfolio value, and Task 1 formatting/weight helpers.
- Produces: `PortfolioPositions({ positions, displayCurrency, totalValue })` and `PortfolioEmptyState({ availableCash, displayCurrency })`.

- [ ] **Step 1: Write the failing desktop position test**

Render one JPY holding inside a USD portfolio and assert:

```tsx
expect(screen.getByRole("link", { name: "7203.T" })).toHaveAttribute("href", "/stocks/7203.T");
expect(screen.getByText("¥2,800")).toBeVisible();
expect(screen.getByText("$18,900.00")).toBeVisible();
expect(screen.getByText("14.72%")).toBeVisible();
expect(screen.getByText("Gain +$2,100.00", { exact: false })).toBeVisible();
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-positions.test.tsx`

Expected: FAIL because `PortfolioPositions` does not exist.

- [ ] **Step 3: Implement the semantic desktop table and mobile rows**

Desktop uses `<Table>` with Symbol/Company, Quantity, Avg cost, Last EOD, Market value, Unrealized P&L/Return, and Portfolio weight. Mobile uses labelled rows in `md:hidden`; desktop uses `hidden md:block`. Both include one restrained Trade link and native/display currency context.

- [ ] **Step 4: Add failing empty-state and reservation tests**

Assert reserved quantity produces `available` secondary text, and empty positions render available cash plus links to `/markets` and `/trade` without allocation/risk placeholders.

- [ ] **Step 5: Run the tests and confirm RED for empty/reserved states**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-positions.test.tsx`

Expected: FAIL until reservation copy and `PortfolioEmptyState` exist.

- [ ] **Step 6: Complete empty and reservation behavior**

Ensure zero/negative/unknown latest values use an em dash where required and no mixed-currency number lacks a label.

- [ ] **Step 7: Run focused and full unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-positions.test.tsx`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass.

- [ ] **Step 8: Commit positions and empty state**

```powershell
git add -- apps/web/components/portfolio-positions.tsx apps/web/components/portfolio-empty-state.tsx apps/web/tests/unit/portfolio-positions.test.tsx
git commit -m "feat(web): rebuild portfolio positions"
```

---

### Task 5: Options, pending orders, and income panels

**Files:**
- Create: `apps/web/components/portfolio-options.tsx`
- Create: `apps/web/components/portfolio-orders.tsx`
- Create: `apps/web/components/portfolio-income.tsx`
- Modify: `apps/web/app/(product)/(authed)/orders/actions.ts`
- Create: `apps/web/tests/unit/portfolio-secondary-panels.test.tsx`
- Create: `apps/web/tests/unit/order-actions.test.ts`

**Interfaces:**
- Consumes: `PortfolioOption[]`, `PendingOrder[] | null`, `DividendSummary | null`, positions, display currency, existing `closeOptionAction`, and existing `cancelOrderAction`.
- Produces: `PortfolioOptions`, `PortfolioOrders`, and `PortfolioIncome` server-presentational components.

- [ ] **Step 1: Write failing option currency tests**

Assert an option row presents strike/native value in JPY, premium paid in USD, current value/P&L in the portfolio display currency, and no Greeks or implied-volatility labels.

- [ ] **Step 2: Run the secondary-panel tests and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-secondary-panels.test.tsx`

Expected: FAIL because the new panels do not exist.

- [ ] **Step 3: Implement the options panel from `portfolio.option_positions`**

Include the existing Close form with `option_id`; do not import or call `listOptionsPositions`. Add concise desktop/mobile rows and a true no-options empty state.

- [ ] **Step 4: Add failing orders and cancellation-revalidation tests**

```tsx
expect(screen.getByText("Native quote")).toBeVisible();
expect(screen.getByText("180.00")).toBeVisible();
expect(screen.queryByText("$180.00")).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: "Cancel AAPL buy limit order" })).toBeVisible();
```

Mock `next/cache` and assert `cancelOrderAction` calls `revalidatePath("/portfolio")` after the existing `/orders` and ticker revalidation behavior.

- [ ] **Step 5: Run tests and confirm the new assertions fail**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-secondary-panels.test.tsx tests/unit/order-actions.test.ts`

Expected: FAIL until order presentation and Portfolio revalidation are implemented.

- [ ] **Step 6: Implement pending orders and action revalidation**

Render `null` as temporarily unavailable and `[]` as no pending orders. Use quantity/date/order-type formatters, explicit BUY/SELL text, native quote labels without currency symbols, cancellation, and a link to `/orders`.

- [ ] **Step 7: Add failing income currency tests**

Assert YTD/history say USD, a projected `7203.T` payment uses JPY from the matching position, an unmatched projection says `Currency unavailable`, and `null` is distinct from a successful no-income payload.

- [ ] **Step 8: Run the income tests and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-secondary-panels.test.tsx`

Expected: FAIL until income currency joins and failure states exist.

- [ ] **Step 9: Implement the income panel**

Keep YTD summary first, upcoming projections second, and credited history last. Apply Task 1 native-currency joins without FX conversion.

- [ ] **Step 10: Run focused and full unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-secondary-panels.test.tsx tests/unit/order-actions.test.ts`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass.

- [ ] **Step 11: Commit the secondary operational panels**

```powershell
git add -- apps/web/components/portfolio-options.tsx apps/web/components/portfolio-orders.tsx apps/web/components/portfolio-income.tsx "apps/web/app/(product)/(authed)/orders/actions.ts" apps/web/tests/unit/portfolio-secondary-panels.test.tsx apps/web/tests/unit/order-actions.test.ts
git commit -m "feat(web): integrate portfolio options orders and income"
```

---

### Task 6: Equity exposure and top movers

**Files:**
- Replace responsibility in: `apps/web/components/portfolio-analytics.tsx`
- Create: `apps/web/tests/unit/portfolio-insights.test.tsx`

**Interfaces:**
- Consumes: `PortfolioAnalytics | null` and display currency.
- Produces: `PortfolioInsights({ analytics, hasEquityPositions })` with unavailable, hidden, and populated states.

- [ ] **Step 1: Write failing insight semantics tests**

```tsx
expect(screen.getByRole("heading", { name: "Equity sector allocation" })).toBeVisible();
expect(screen.getByText("Cash and options excluded")).toBeVisible();
expect(screen.getByRole("heading", { name: "Top movers" })).toBeVisible();
expect(screen.getByText("Detractors")).toBeVisible();
expect(screen.queryByText(/contributor/i)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the insight tests and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-insights.test.tsx`

Expected: FAIL because the existing analytics component uses the old card hierarchy and labels.

- [ ] **Step 3: Rebuild the component as allocation and mover insights**

Remove KPI cards from this component. Render a CSS stacked exposure bar with a neutral categorical palette plus ranked sector rows. Render separate Gainers and Detractors lists with signed return and display-currency P&L. Use separators/tonal surfaces rather than nested Cards.

- [ ] **Step 4: Add failing empty and unavailable tests**

Assert no equity positions render no allocation/movers region, while `analytics={null}` with equity positions renders `Portfolio insights are temporarily unavailable.`

- [ ] **Step 5: Run the tests and confirm state distinctions fail**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-insights.test.tsx`

Expected: FAIL until the hidden and unavailable states differ.

- [ ] **Step 6: Complete insight state handling and responsive layout**

Use two columns at `lg`, one column below, stable keys, linked tickers, visible focus, and explicit signed values.

- [ ] **Step 7: Run focused and full unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-insights.test.tsx`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all tests pass.

- [ ] **Step 8: Commit insights**

```powershell
git add -- apps/web/components/portfolio-analytics.tsx apps/web/tests/unit/portfolio-insights.test.tsx
git commit -m "feat(web): clarify portfolio exposure insights"
```

---

### Task 7: Server orchestration and complete workspace composition

**Files:**
- Create: `apps/web/components/portfolio-workspace.tsx`
- Create: `apps/web/lib/portfolio-data.ts`
- Replace: `apps/web/app/(product)/(authed)/portfolio/page.tsx`
- Modify: `apps/web/app/(product)/(authed)/portfolio/loading.tsx`
- Delete: `apps/web/components/options-positions.tsx` only if no remaining import exists
- Create: `apps/web/tests/unit/portfolio-workspace.test.tsx`
- Create: `apps/web/tests/unit/portfolio-data.test.ts`

**Interfaces:**
- Consumes: all focused components and API results from Tasks 1–6.
- Produces: `PortfolioWorkspace(props)`, `loadPortfolioData(range)`, and an async route that fetches each resource exactly once through that loader.

- [ ] **Step 1: Write a failing composition test for a populated workspace**

Render `PortfolioWorkspace` with a display-currency portfolio, history, analytics, pending order, and dividend payload. Assert one dominant Portfolio heading, performance region before tabs, Positions selected, allocation after operational content, and no old `Dividend income`/`Options positions` top-level sequence.

- [ ] **Step 2: Run the workspace test and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-workspace.test.tsx`

Expected: FAIL because `PortfolioWorkspace` does not exist.

- [ ] **Step 3: Implement the presentational workspace composition**

Compose `PortfolioPerformance`, `PortfolioMetrics`, `PortfolioTabs`, panels, and `PortfolioInsights` inside a full-width `px-4 py-6 sm:px-6 lg:px-8` workspace. For zero stock and option positions, use `PortfolioEmptyState` and omit chart/risk/insight noise while keeping operational tabs reachable.

- [ ] **Step 4: Add failing orchestration/source-boundary assertions**

Test `loadPortfolioData(range)` with mocked API modules. Assert:

```ts
expect(getPortfolio).toHaveBeenCalledTimes(1);
expect(getPortfolioHistory).toHaveBeenCalledWith(365);
expect(listOrders).toHaveBeenCalledWith("pending");
expect(listOptionsPositions).not.toHaveBeenCalled();
expect(result.orders).toBeNull(); // rejected optional request
```

- [ ] **Step 5: Run the orchestration test and confirm RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-workspace.test.tsx tests/unit/portfolio-data.test.ts`

Expected: FAIL until the route data loader uses the new parallel orchestration.

- [ ] **Step 6: Replace the route with one parallel server orchestration**

Implement `loadPortfolioData(range)` in the server-only data module using `Promise.all` for portfolio, history, analytics, `listOrders("pending")`, and dividends, converting only optional failures to `null`. The route parses `range` and `tab`, calls the loader once, and passes the portfolio's embedded options. Remove `listOptionsPositions`. Update the loading state to mirror the ledger, chart, metrics, and table rhythm without restoring card soup.

- [ ] **Step 7: Remove the obsolete options component if unreferenced**

Run: `rg -n "OptionsPositions|options-positions" apps/web`

Expected: no production/test imports. Delete `apps/web/components/options-positions.tsx`; otherwise leave it and document its remaining consumer.

- [ ] **Step 8: Run focused tests, typecheck, and full unit suite**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/portfolio-workspace.test.tsx tests/unit/portfolio-data.test.ts`

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all checks pass.

- [ ] **Step 9: Commit the assembled workspace**

```powershell
git add -- apps/web/components/portfolio-workspace.tsx apps/web/lib/portfolio-data.ts "apps/web/app/(product)/(authed)/portfolio/page.tsx" "apps/web/app/(product)/(authed)/portfolio/loading.tsx" apps/web/components/options-positions.tsx apps/web/tests/unit/portfolio-workspace.test.tsx apps/web/tests/unit/portfolio-data.test.ts
git commit -m "feat(web): assemble portfolio monitoring workspace"
```

---

### Task 8: Database readiness and targeted Portfolio E2E

**Files:**
- Create: `apps/web/tests/e2e/portfolio.spec.ts`

**Interfaces:**
- Consumes: running repository API/database, authenticated signup flow, and completed `/portfolio` UI.
- Produces: regression coverage for populated/new portfolio, range state, operational tabs, stock links, and mobile readability.

- [ ] **Step 1: Audit the existing migration state without modifying schema files**

Run: `uv --directory apps/api run alembic current`

Run: `uv --directory apps/api run alembic heads`

Run: `uv --directory apps/api run alembic history --verbose`

Expected: identify whether the local database is behind the repository head, including the migration that adds `pending_orders.cancel_reason`.

- [ ] **Step 2: Apply repository migrations to the local test database**

Run: `pnpm.cmd run api:migrate`

Expected: Alembic reaches the repository head with no migration-file changes. Re-run `uv --directory apps/api run alembic current` and record the resulting revision.

- [ ] **Step 3: Write the targeted Playwright tests**

Add tests that sign up a unique user, visit `/portfolio`, and assert:

```ts
await expect(page.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
await expect(page.getByText("Latest EOD valuation", { exact: false })).toBeVisible();
await page.getByRole("link", { name: "1Y" }).click();
await expect(page).toHaveURL(/range=1y/);
await page.getByRole("tab", { name: /Orders/ }).click();
await expect(page).toHaveURL(/tab=orders/);
```

Add a 390×844 viewport test asserting tabs fit/scroll intentionally, the total value is visible, and the empty/new holding state exposes Explore Markets and Trade without document-level horizontal overflow.

- [ ] **Step 4: Run targeted E2E and confirm any failure is product/environment specific**

Run: `pnpm.cmd --filter @stockviz/web e2e -- tests/e2e/portfolio.spec.ts`

Expected: PASS. If startup fails, capture the exact API/database/browser error and fix only repository/environment setup; do not weaken assertions.

- [ ] **Step 5: Run the full Playwright suite**

Run: `pnpm.cmd --filter @stockviz/web e2e`

Expected: all configured Playwright tests pass. Separate pre-existing environment failures from Phase 3 regressions.

- [ ] **Step 6: Commit E2E coverage**

```powershell
git add -- apps/web/tests/e2e/portfolio.spec.ts
git commit -m "test(web): cover portfolio workspace flows"
```

---

### Task 9: Final quality gates, visual QA, and branch review

**Files:**
- Modify only files implicated by verified failures or visual defects.

**Interfaces:**
- Consumes: complete Phase 3 implementation.
- Produces: verified, review-ready branch and final evidence.

- [ ] **Step 1: Run formatting/lint diagnostics**

Run: `pnpm.cmd --filter @stockviz/web lint`

Expected: PASS. Apply Biome formatting only to changed files when diagnostics require it.

- [ ] **Step 2: Run TypeScript and unit tests**

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: PASS with all new and existing tests.

- [ ] **Step 3: Run the production build**

Run: `pnpm.cmd --filter @stockviz/web build`

Expected: Next.js production build completes successfully.

- [ ] **Step 4: Run targeted and full Playwright again after the production build**

Run: `pnpm.cmd --filter @stockviz/web e2e -- tests/e2e/portfolio.spec.ts`

Run: `pnpm.cmd --filter @stockviz/web e2e`

Expected: PASS when the configured browser/API/database runtime is available.

- [ ] **Step 5: Perform visual QA if the in-app browser runtime is available**

Inspect `/portfolio` at 1600×1000, 1440×900, 1280×800, and 390×844 in dark and light themes. Capture:

- `artifacts/phase3/portfolio-1600-dark.png`
- `artifacts/phase3/portfolio-1440-dark.png`
- `artifacts/phase3/portfolio-1280-dark.png`
- `artifacts/phase3/portfolio-desktop-light.png`
- `artifacts/phase3/portfolio-mobile-dark.png`
- `artifacts/phase3/portfolio-mobile-light.png`
- `artifacts/phase3/portfolio-empty.png` when practical

Check total-value prominence, chart height, metrics density, tabs, currency labels, position rows, allocation, movers, empty states, overflow, focus, and both theme contrasts. If the runtime is unavailable, record that limitation and do not fabricate screenshots.

- [ ] **Step 6: Review the complete diff and Git state**

Run: `git diff 86792b6d3ebe7056f6f1aafcff0948b8d6cec8ed...HEAD --stat`

Run: `git diff 86792b6d3ebe7056f6f1aafcff0948b8d6cec8ed...HEAD --check`

Run: `git status --short --branch`

Run: `git rev-list --count 86792b6d3ebe7056f6f1aafcff0948b8d6cec8ed..HEAD`

Expected: no whitespace errors, no unintended files, and a clean worktree.

- [ ] **Step 7: Request code review**

Use the `superpowers:requesting-code-review` skill against the base commit and address only evidence-backed Phase 3 findings. Re-run the affected focused test before the full gates.

- [ ] **Step 8: Commit verified review fixes if any**

Stage the exact files changed by the evidence-backed review fix, then run `git commit -m "fix(web): harden portfolio workspace states"`.

If no fixes are required, leave the clean verified HEAD unchanged.
