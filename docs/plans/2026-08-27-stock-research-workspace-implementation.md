# Stock Research Workspace Implementation Plan

> Implement incrementally with tests first. Keep the Phase 1 shell, public routes, backend contracts, and `PriceChart` internals unchanged.

**Goal:** Recompose `/stocks/[ticker]` as a responsive research and contextual paper-trading workspace using existing StockViz APIs and server actions.

**Architecture:** The stock route remains a server-component data orchestrator. It fetches public research data plus one authenticated account context, derives reliable display metrics, and passes serializable props into focused server and client components. Client state is limited to chart navigation, tabs, order-entry state, alerts/watchlist, simulated indicative price, and the mobile dialog sheet.

**Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind 4, Radix UI, shadcn primitives, Vitest/Testing Library, Playwright.

---

## Task 1: Pure stock workspace helpers

**Files:**

- Create: `apps/web/lib/stock-workspace.ts`
- Test: `apps/web/tests/unit/stock-workspace.test.ts`

1. Write failing tests for quantity rounding, buy and sell percentage sizing, cross-currency shortcut eligibility, notional estimates, position return/allocation, period return, and bar metrics.
2. Run the focused test and confirm it fails because the module is absent.
3. Implement small pure helpers with explicit null handling and six-decimal floor rounding.
4. Run the focused test and confirm it passes.

## Task 2: Preserve stock analysis state through global search

**Files:**

- Modify: `apps/web/components/global-ticker-search.tsx`
- Modify: `apps/web/tests/unit/global-ticker-search.test.tsx`

1. Extend the navigation mock and add a failing test proving that selecting another ticker while on `/stocks/[ticker]?tf=...&indicators=...` carries only the supported chart parameters.
2. Implement destination construction with `usePathname` and `useSearchParams`.
3. Re-run the focused component test.

## Task 3: Reusable contextual trade ticket

**Files:**

- Create: `apps/web/components/contextual-trade-ticket.tsx`
- Create: `apps/web/components/mobile-trade-sheet.tsx`
- Test: `apps/web/tests/unit/contextual-trade-ticket.test.tsx`
- Modify: `apps/web/app/(product)/(authed)/trade/actions.ts`

1. Add failing component tests for guest sign-in state, authenticated market/limit switching, side semantics, safe sizing shortcuts, position-protection disclosure, estimates, and validation.
2. Build a locked-ticker client ticket that calls existing trade/order server actions and consumes server-provided account context.
3. Use Market and Limit as primary choices; reveal Stop-loss and Take-profit only for available holdings.
4. Add route-aware revalidation to existing actions without changing API behavior.
5. Wrap the same ticket in a Radix Dialog bottom sheet for mobile, with Buy/Sell launch buttons and accessible labelling.
6. Run focused component tests.

## Task 4: Research workspace presentation components

**Files:**

- Create: `apps/web/components/security-header.tsx`
- Create: `apps/web/components/stock-chart-toolbar.tsx`
- Create: `apps/web/components/stock-metrics-strip.tsx`
- Create: `apps/web/components/position-summary.tsx`
- Create: `apps/web/components/ticker-orders.tsx`
- Create: `apps/web/components/stock-research-tabs.tsx`
- Modify: `apps/web/components/live-price-badge.tsx`
- Modify: `apps/web/components/watchlist-toggle.tsx`
- Modify: `apps/web/components/alert-form.tsx`
- Modify: `apps/web/components/news-list.tsx`
- Modify: `apps/web/components/comments-section.tsx`
- Test: `apps/web/tests/unit/stock-workspace-components.test.tsx`

1. Add focused rendering tests for financial hierarchy, quiet indicative-price semantics, metric labels, position/order empty and populated states, and accessible tab behavior.
2. Implement server/presentational components with restrained panels and tabular numerals.
3. Move indicators into an accessible Radix dropdown while keeping timeframe links visible and URL-driven.
4. Add embedded/compact variants to existing news and discussion components so other routes retain their current layout.
5. Refine existing personal actions for compact header use and guest sign-in behavior.
6. Run focused tests.

## Task 5: Server orchestration and responsive composition

**Files:**

- Modify: `apps/web/app/(product)/stocks/[ticker]/page.tsx`
- Remove from route usage only: `apps/web/components/stock-sidebar.tsx`
- Modify: `apps/web/app/globals.css` only if a semantic utility/token is genuinely missing

1. Replace the sequential stock sidebar-oriented fetch flow with parallel public data fetches and a single authenticated context fetch.
2. Request enough bar history for reliable 52-week metrics without duplicating a request where the selected timeframe already covers it.
3. Include RSI in the indicator request for metrics while filtering unselected overlays from the chart.
4. Compose the security header, chart toolbar/chart, metric strip, sticky desktop ticket, mobile trade sheet, and research tabs.
5. Keep guest research fully visible and personal data/actions gracefully gated.
6. Verify that the local stock sidebar is no longer rendered and the chart width is reclaimed.

## Task 6: Integration and browser tests

**Files:**

- Inspect/modify existing Playwright fixtures and authentication helpers
- Create or modify the smallest relevant stock-workspace Playwright spec

1. Add coverage for guest research rendering, chart query controls, guest sign-in affordance, and mobile trade-sheet open/close.
2. Add authenticated ticket/watchlist/alert coverage only if existing fixtures provide a reliable signed-in state.
3. Run the focused Playwright spec; report missing browser/runtime or service dependencies distinctly.

## Task 7: Full verification and handoff evidence

1. Run `pnpm.cmd --filter @stockviz/web test`.
2. Run `pnpm.cmd --filter @stockviz/web lint`.
3. Run `pnpm.cmd --filter @stockviz/web typecheck`.
4. Run `pnpm.cmd --filter @stockviz/web build`.
5. Run relevant and full Playwright suites if the configured environment supports them.
6. Inspect the final diff for unrelated files, generated agent-rule changes, accessibility regressions, duplicated requests, and hardcoded colors.
7. Record final branch status, commits ahead of the Phase 1 base, and final HEAD.
