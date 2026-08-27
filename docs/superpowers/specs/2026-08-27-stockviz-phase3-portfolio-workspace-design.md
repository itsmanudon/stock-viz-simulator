# StockViz Phase 3 Portfolio Workspace Design

**Date:** 2026-08-27

**Branch:** `redesign/ui-phase3-portfolio-workspace`

**Base commit:** `86792b6d3ebe7056f6f1aafcff0948b8d6cec8ed`

## Objective

Redesign the authenticated `/portfolio` route into a performance-first monitoring workspace that answers three questions quickly: how the portfolio is performing, what is driving its current state, and what the user owns or has exposed. The implementation will inherit the Phase 1 application shell and Phase 2 research workspace, preserve existing APIs and routes, and avoid redesigning adjacent products.

## Current-State Findings

- The page currently presents four portfolio summary cards, four analytics cards, allocation and mover cards, a lower performance chart, dividends, stock positions, and options positions in one long sequence. This gives primary and secondary data equal weight.
- Portfolio, history, dividends, analytics, and options are fetched in parallel. Options are fetched separately even though the portfolio response already includes multi-currency option positions.
- Portfolio totals, equity market values, option market values, and unrealized P&L are already converted by the backend into the user's display currency.
- Position average cost, latest close, and native market value remain in each security's native currency.
- NAV snapshots are written in USD. Selected-range absolute and percentage changes derived from history are therefore USD NAV performance, even when the current portfolio is displayed in another currency.
- Portfolio analytics are calculated across all available history, not the range selected for the chart.
- Sector allocation covers equity positions only. It excludes cash and options.
- Movers are ranked by position return and are not formal contribution-to-return attribution.
- Credited dividend income and history are USD. Projected dividends are calculated from each security's native dividend and quantity, but the response does not carry an explicit currency field; the native currency can be joined from the matching position.
- Pending orders are available through the existing orders API and cancellation action. Trigger prices do not carry currency metadata.
- Current failure fallbacks convert some upstream failures into empty arrays, which can misrepresent unavailable data as a genuinely empty portfolio subsystem.

## Approaches Considered

### Chosen: performance ledger, operational tabs, persistent insights

Use one continuous performance surface for the dominant value, selected-range NAV change, range control, chart, and compact metrics. Put detailed datasets behind URL-backed Positions, Options, Orders, and Income tabs. Keep current equity allocation and movers visible below the active dataset when the portfolio has equity holdings.

This approach establishes a clear reading order, keeps holdings operationally central, preserves exposure context without hiding it in an analytics tab, and adapts cleanly to empty and mobile states.

### Rejected: two-thirds chart with a permanent one-third insights rail

A fixed allocation/movers rail makes a strong wide-screen dashboard but compresses the chart and table at the important 1280px target after the application sidebar is accounted for. It also leaves an awkward empty column for new portfolios.

### Rejected: move analytics and exposure into another tab

This reduces vertical length but hides the answer to "why am I doing that way?" behind navigation. Allocation, risk context, and movers should remain discoverable alongside the primary holdings workflow.

## Information Architecture

The Portfolio workspace has four regions:

1. **Performance ledger:** page identity, Trade action, total value, selected-range USD NAV change, latest snapshot semantics, range controls, and the equity curve.
2. **Metrics strip:** current balance-sheet values in display currency plus all-history risk/return analytics with explicit scope.
3. **Operational workspace:** URL-backed Positions, Options, Orders, and Income tabs.
4. **Exposure insights:** equity sector allocation and top position movers, shown only when meaningful.

The page uses the Phase 1 workstation width. Structure comes from spacing, quiet tonal surfaces, and ledger-like hairline separators rather than a grid of generic cards.

## Performance Ledger

The top-level heading is `Portfolio`, accompanied by a restrained link to `/trade`. The total portfolio value is the dominant number and uses the user's display currency. Supporting copy states that the valuation uses the latest available end-of-day closes rather than realtime prices.

When two or more NAV snapshots exist for the selected range, the header shows the absolute and percentage change between the first and latest point. The label explicitly names the range and basis, for example `3M USD NAV change`. The snapshot date appears as quiet metadata. Gain/loss uses sign, wording, and semantic color rather than color alone.

Range controls are `1M`, `3M`, `1Y`, and `All`, mapped to the existing history API's `30`, `90`, `365`, and unbounded modes. `3M` is the default. The `range` query parameter is preserved so the view is shareable and browser navigation works.

The existing `EquityCurve` remains the chart implementation. It will be adapted only to fit the primary surface, respect theme tokens, and expose a concise accessible description. Insufficient history produces a compact explanation instead of a flat line or invented performance.

## Metrics Strip

The metrics strip prioritizes:

- Available cash in display currency
- Invested equities in display currency
- Options exposure in display currency when nonzero or option positions exist
- All-history return when analytics exist
- Sharpe ratio when enough history exists
- Maximum drawdown when enough history exists

Annualized return may replace a lower-value item at wider breakpoints but will not create a second row of equal-priority cards. Analytics are labelled `All-history` and may include the available history-day count so they cannot be mistaken for the selected chart range.

On mobile, metrics wrap into two-column ledger cells. For a new portfolio, the strip shows only meaningful balances and omits meaningless zero risk statistics.

## Operational Tabs and URL State

Accessible Radix tabs organize `Positions`, `Options`, `Orders`, and `Income`. `Positions` is the default. The `tab` query parameter preserves deep links and browser back/forward behavior, while tab changes retain the selected `range` parameter.

The route page remains a server component. A small client tab controller owns only Radix interaction and URL synchronization; it receives already-fetched content rather than triggering new data requests.

## Positions

Positions are the primary detailed dataset. The desktop table includes:

- Symbol and company
- Quantity
- Average cost in native currency
- Latest EOD price in native currency
- Market value in display currency
- Unrealized P&L and return in display currency/percentage
- Portfolio weight derived from display-currency position value divided by current total value

Ticker names link to the Phase 2 stock workspace. Foreign-security native values remain visible as secondary context instead of being silently converted or mixed with display-currency totals. Numeric columns use tabular financial typography and align consistently. Rows use a quiet hover treatment, with one restrained Trade link rather than an action toolbar.

Mobile uses a dedicated holding-row composition rather than an eight-column horizontally scrolling table. Each row prioritizes symbol/company, display-currency market value, quantity, return/P&L, and average/latest native prices. The desktop table remains a semantic table; the mobile representation retains meaningful labels for screen readers.

No new sorting behavior is included. The backend's current position order is preserved to keep this phase focused and avoid introducing client hydration solely for sorting.

## Options

The Options tab uses `portfolio.option_positions`, eliminating the separate options-position request. Available fields determine the presentation:

- Underlying and link to its stock workspace
- Call or put
- Strike in the underlying's native currency
- Expiry
- Contract quantity
- Premium paid in USD
- Current estimated value in display currency
- Unrealized P&L in display currency

The UI does not show Greeks, implied volatility, or realtime quote semantics. Foreign option values may include native market value as quiet secondary context when it prevents currency ambiguity. An empty state explains that no option positions are open without crowding the page.

## Orders

The page fetches pending orders once through the existing orders API. The Orders tab shows ticker, side, type, quantity, native quote trigger/limit, status, and creation date. It reuses the existing cancellation server action and adds `/portfolio` revalidation so cancellation updates the integrated view. A link to `/orders` preserves the standalone detailed workflow.

Because pending-order trigger prices have no currency metadata, the UI labels them `Native quote` and does not assign a currency symbol. It will not add per-order symbol requests or infer USD. An upstream order failure produces an unavailable state; a successful empty response produces the true no-pending-orders state.

## Income

The Income tab contains:

1. YTD credited income in USD
2. Upcoming projected dividends, formatted in the matching holding's native currency
3. Credited dividend history in USD

The tab states these currency bases explicitly. If a projected dividend cannot be matched to a position currency, it displays the numeric amount with `currency unavailable` rather than guessing. No dividend forecast beyond the existing API response is introduced.

## Exposure and Movers

`Equity sector allocation` uses the existing analytics response and clearly states that cash and options are excluded. A CSS-based stacked exposure bar and compact ranked rows communicate the largest sectors without adding a chart dependency. Each sector uses a stable neutral/gold-adjacent palette that does not reuse positive/negative colors as categorical decoration.

`Top movers` presents positive and negative position performers in two compact groups. Rows show ticker, return percentage, and unrealized P&L in display currency. Labels are `Gainers` and `Detractors`, not contributors, because the backend does not calculate formal attribution.

Allocation and movers disappear for a portfolio without equity positions. Analytics-unavailable states are distinguished from empty exposure.

## Empty and Failure States

A new portfolio keeps the dominant total value and meaningful available cash, then replaces chart, risk analytics, allocation, and movers with one clear starting state. It offers `Explore markets` and `Place a trade` actions without rendering a page of zero metrics.

No options, no pending orders, and no dividends each receive concise dataset-specific copy inside their tabs. Insufficient NAV history explains that performance and risk analytics populate as daily snapshots accumulate.

History, analytics, orders, and dividend requests use nullable result states:

- `null` means the resource could not be loaded and renders `temporarily unavailable`.
- `[]` or an empty successful payload means there is genuinely no data and renders the corresponding empty state.

The required portfolio fetch remains the route's authoritative failure boundary.

## Server Orchestration and Data Flow

After authentication, the server route parses and validates `range` and `tab`, then performs one parallel orchestration:

- `getPortfolio()`
- `getPortfolioHistory(days)`
- `getPortfolioAnalytics()`
- `listOrders("pending")`
- `getDividends()`

Independent optional resources resolve to `null` on failure. The page removes `listOptionsPositions()` because the portfolio payload already contains the required option data. Child components receive prepared data and do not refetch.

Pure server helpers derive selected-range NAV change, position weight, and projected-dividend currency joins. These helpers do not perform new FX conversion. Client components are limited to the existing equity chart and the URL-synchronized tab controller.

## Component Boundaries

- `PortfolioPage`: authentication, query parsing, parallel data orchestration, and composition.
- `PortfolioPerformance`: dominant value, range performance semantics, range controls, chart, and insufficient-history state.
- `PortfolioMetrics`: compact current-value and all-history analytics ledger.
- `PortfolioTabs`: accessible client tab selection and URL synchronization.
- `PositionsTable`: desktop semantic table and mobile holding rows.
- `PortfolioOptions`: portfolio-payload option positions and empty state.
- `PortfolioOrders`: portfolio-wide pending orders, cancellation, failure, and empty states.
- `PortfolioIncome`: YTD, projected, and historical dividend content with explicit currencies.
- `PortfolioInsights`: equity-only allocation and top movers.
- `portfolio-view-model`: pure range, return, weight, and currency-presentation helpers.

Files remain focused by responsibility; ticker-specific Phase 2 components are reused only where their interfaces fit naturally. Portfolio-wide order presentation will share formatting/action primitives without forcing the ticker-specific `TickerOrders` component into a different role.

## Responsive Design

At 1600px and 1440px, the performance ledger uses the full workspace and the chart has enough height to remain the primary visual surface. At 1280px, it stays a single main column rather than competing with a permanent insight rail. Operational content and insights use the available width below.

At mobile width:

- The dominant value and range change stack without truncation.
- Range controls remain touch-sized and do not imply unavailable intraday periods.
- The chart remains full width and legible.
- Metrics wrap into compact ledger cells.
- Tabs use an accessible horizontal overflow region if labels cannot fit.
- Positions and options use purpose-built mobile rows rather than wide tables.
- Allocation rows and movers stack vertically.

The page prevents document-level horizontal overflow while allowing a deliberately scrollable tab list when necessary.

## Visual System

The page reuses the Phase 1 semantic tokens, restrained gold, positive/negative semantics, platform interface type, and tabular financial typography. No new font, global aesthetic, or chart dependency is introduced.

The signature element is a **portfolio ledger line**: one continuous alignment joining total value, range return, chart, and metrics through disciplined whitespace and hairline separators. It extends the workstation's ledger language without introducing gradients, glass effects, oversized radii, or a generic dashboard-card grid.

Gold denotes brand, selection, focus, and the primary Trade action. Positive and negative colors communicate performance and side semantics only. Allocation categories use neutral categorical tones. Surfaces are quiet, radii remain restrained, and shadows are reserved for overlays already present in the application shell.

## Accessibility

- Preserve the Phase 1 skip link and main landmark.
- Use a single page-level heading followed by semantic section headings.
- Use Radix tabs for keyboard navigation, ARIA relationships, and visible focus.
- Preserve semantic desktop tables with labelled headers and links.
- Give mobile financial rows explicit accessible labels.
- Include plus/minus signs and gain/loss wording so color is not the sole indicator.
- Give every icon-only action an accessible name.
- Ensure range controls expose selected state and retain focus-visible treatment.
- Give the chart a textual description of range, latest snapshot, and change.
- Respect existing reduced-motion preferences and avoid new decorative animation.

## Test Strategy

Implementation follows red-green-refactor.

### Unit and component coverage

- Range parsing accepts `1m`, `3m`, `1y`, and `all`, defaults invalid input to `3m`, and maps to the correct API days.
- Selected-range NAV calculations return USD absolute/percentage change only with sufficient valid history.
- Position weight uses display-currency values and handles zero total value.
- Projected-dividend currency joins use the matching position's native currency and never assume USD.
- Tabs preserve `range`, update `tab`, and remain keyboard operable.
- Performance, metrics, positions, options, orders, income, insights, unavailable states, and new-portfolio states render their intended financial semantics.
- Cancellation revalidates `/portfolio` in addition to existing order routes.

### End-to-end coverage

- Authenticated Portfolio renders the dominant value and performance range controls.
- Position tickers link to the stock workspace.
- Options, Orders, and Income tabs are usable and URL-addressable.
- Mobile holdings remain readable and tabs remain usable.
- A fixture or controlled state covers a genuinely empty portfolio where practical.

### Quality gates

- Frontend lint
- TypeScript typecheck
- Frontend unit tests
- Production build
- Targeted Portfolio Playwright coverage
- Full Playwright suite after applying the repository's existing database migrations

The database will be brought to the repository migration head before authenticated E2E validation. No schema workaround or migration change belongs in this UI phase.

## External Reference Principles

- **Origin:** performance-first portfolio hierarchy and restrained position context.
- **Monarch:** dominant primary value and chart-led investment overview.
- **Fey:** calm dark-mode hierarchy, compact data presentation, and precise typography.
- **Koyfin:** one-page organization of performance, risk, exposure, and holdings.

These references inform hierarchy and interaction principles only. The implementation retains StockViz's existing identity and data model.

## Scope Boundaries

- No backend model or API changes unless an implementation blocker proves a small change necessary and is separately justified.
- No changes to NAV snapshot currency semantics or analytics calculations.
- No new client-side FX calculations.
- No realtime valuation, benchmarking, formal attribution, option Greeks, tax lots, or portfolio optimization.
- No redesign of Dashboard, Markets, Screener, Backtest, Compare, Recommendations, News, Leaderboard, navigation, stock workspace, standalone Trade, or standalone Orders.
- No large dependency additions or chart-library replacement.

## Completion Criteria

Phase 3 is complete when Portfolio has a performance-first hierarchy, one dominant value and chart surface, a compact metrics ledger, URL-backed operational tabs, high-quality stock and option holdings views, integrated pending orders and income, clear equity-only allocation and movers, accurate multi-currency semantics, thoughtful empty/unavailable states, intentional mobile behavior, and no unrelated product redesign. Relevant lint, typecheck, tests, build, database migration setup, and visual/E2E verification are reported with environment limitations separated from product failures.
