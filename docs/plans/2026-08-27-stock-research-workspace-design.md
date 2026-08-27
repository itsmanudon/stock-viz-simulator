# Stock Research and Contextual Trading Workspace Design

**Date:** 2026-08-27  
**Branch:** `redesign/ui-phase2-stock-workspace`  
**Base:** `5fffb5641509383f083c2373776576e82340db5d`

## Objective

Turn `/stocks/[ticker]` into StockViz's flagship research and paper-trading workspace. A user should be able to identify a security, study its chart and context, understand their relationship to it, and place a simulated order without switching product areas. The Phase 1 application shell, existing routes, trading backend, and `lightweight-charts` implementation remain intact.

## Information Architecture

The workspace is composed of five regions:

1. A security header establishes ticker identity, market metadata, the authoritative latest close, selected-period movement, and personal actions.
2. A dominant chart region contains restrained timeframe and indicator controls around the existing chart.
3. A contextual paper-trading ticket sits beside the chart on desktop and opens as a bottom sheet on mobile.
4. A compact metric strip summarizes reliable price and technical context derived from existing bars.
5. Accessible research tabs organize Overview, News, Position & Orders, and Discussion.

The legacy stock-specific symbol sidebar is removed. Phase 1 already provides global navigation and ticker search, and retaining both sidebars would reduce the chart to an unsuitable width at 1280px. Global ticker search will preserve the current stock page's timeframe and indicator query parameters when switching securities.

## Security Header and Price Semantics

The header presents ticker, company name, exchange, sector, currency, latest cached close, and return for the selected chart period. Watchlist and alert controls remain available, with concise sign-in affordances for guests.

The latest cached end-of-day close is the authoritative displayed price and the basis for market-order estimates. The existing simulated stream is retained as a quiet secondary indicative value with an accessible explanation that it is simulated from the latest close. It will not use a pulsating “live” treatment or imply an exchange-quality realtime quote.

## Desktop Composition

At workstation widths, the primary region uses a two-column grid:

- The chart occupies the flexible primary column.
- A sticky 320–340px trading ticket occupies the right column.

At approximately 1280px, the chart remains usable after accounting for the Phase 1 application sidebar. The metric strip follows the chart and the research tabs use the available workspace width below the primary region. Visual grouping relies on tonal surfaces, separators, spacing, and typography rather than nested cards.

## Mobile Composition

The security header condenses, the chart uses the full content width, metrics wrap into a compact grid, and research tabs remain horizontally usable. Buy and Sell actions open an accessible bottom-anchored dialog sheet with the chosen side preselected. The sheet uses Radix focus management, Escape dismissal, labelled controls, and an explicit close action. The full ticket is not permanently inserted into the mobile research flow.

## Trading Ticket

The ticket is locked to the viewed ticker and reuses the existing `placeTradeAction` and `placeOrderAction` backend flows.

Primary order types are Market and Limit. Stop-loss and Take-profit are progressively disclosed as position-protection actions only when the authenticated user has available shares. This preserves the existing capabilities without giving four uncommon controls equal visual priority.

The ticket shows:

- selected ticker and side;
- order type and quantity;
- limit or trigger price when required;
- estimated notional with its price basis;
- available cash or buying power;
- held and available quantity when selling;
- inline validation, pending state, and server feedback;
- a clear side-specific submission action.

Sizing shortcuts use only real account data:

- Sell shortcuts use `available_quantity`, which excludes reserved shares.
- Buy shortcuts use `available_cash` and the effective order price, rounded down to the backend's six-decimal quantity precision.
- Buy shortcuts are omitted when the symbol currency differs from the portfolio display currency because no safe conversion rate is available.
- Market estimates are labelled as estimates at the latest cached close; Limit and protective estimates use the entered limit or trigger price.

Guests see the research workspace and a compact sign-in prompt inside the ticket or personal-action surface, never a page-level authentication wall.

## Position and Order Context

The stock page fetches the authenticated user's portfolio once and uses the matching position to show quantity, average cost, current value, unrealized P&L, return, and allocation when derivable. Users without a position receive no empty position card.

Pending orders are fetched once through the existing orders API and filtered by ticker on the server. Compact order rows show side, type, quantity, price, and status. Existing cancellation behavior is reused and enhanced only as needed to revalidate the stock route. No new order model or backend endpoint is introduced.

## Chart Controls and URL State

The existing `PriceChart` implementation and indicator calculations remain unchanged. Timeframes remain directly visible because they are a frequent analytical action. Indicators move into one labelled menu with clear selected state. All selections continue to update `tf` and `indicators` search parameters so links remain shareable and browser back/forward behavior is preserved.

Global ticker navigation from a stock route carries those chart parameters to the destination ticker.

## Metrics

The metric strip uses only existing bars and indicators:

- Open
- High
- Low
- Previous close
- Volume
- 52-week range
- RSI 14 when available

The server requests enough bars to calculate the 52-week range without duplicating requests where the selected timeframe already contains them. RSI is obtained through the existing indicator endpoint and displayed on the chart only when selected.

No bid/ask spread, realtime claim, financial ratio, or company fundamental is invented.

## Secondary Research

Radix-backed tabs organize:

- **Overview:** available identity, exchange, sector, currency, latest-data timestamp, and a concise explanation of StockViz's data basis.
- **News:** existing ticker news with headline, source, time, summary, and genuine sentiment metadata when supplied.
- **Position & Orders:** current holding and filtered pending orders, with a useful empty state.
- **Discussion:** the existing comments system in an embedded presentation.

Overview is the consistent default. Position information remains visible near the ticket when it is immediately relevant, so authenticated users do not need a different default tab.

## Server and Client Boundaries

The route page remains the server orchestrator. Public market data and authentication are fetched in parallel after ticker validation. Authenticated portfolio, pending orders, and watchlist data are then fetched once each and filtered server-side for the selected ticker.

Server/presentational components handle the security header, metric strip, position summary, order list, and tab content. Client components are limited to real interaction: simulated price streaming, watchlist and alert controls, chart indicator navigation, tabs, ticket state/calculations, and the mobile sheet.

Pure sizing and notional helpers are separated from UI state and covered by focused unit tests. Large trading logic is not copied into the route page.

## Accessibility

The design preserves Phase 1 landmarks and skip navigation. Interactive controls have visible focus states and accessible names. Tabs follow ARIA tab semantics; the mobile sheet traps focus; forms retain explicit labels and error associations. Gain/loss includes signs and textual labels rather than relying on color. Reduced-motion preferences suppress nonessential transitions.

## Performance

Independent server fetches are parallelized. Portfolio and pending orders are not re-fetched by child components. The ticket does not poll. The current simulated-price stream remains the only price update stream, and the chart does not rehydrate for unrelated tab changes.

## Verification Scope

Implementation will add focused unit tests for quantity sizing, estimates, state/URL preservation, and presentational states. Relevant frontend lint, typecheck, unit tests, production build, and Playwright tests will run. Full Playwright coverage will run if its configured browser/runtime is available.

The in-app browser connector currently exposes no browser runtime, so screenshot-based visual QA may be unavailable. This will be reported as an environment limitation rather than substituted with an unsupported browser-control surface.

## Deferred Work

- Standalone `/trade` redesign
- Portfolio workspace redesign
- True realtime quotes or bid/ask data
- Currency conversion for cross-currency sizing
- New fundamentals or valuation data
- Brokerage integrations or changes to the simulation model
