# StockViz Phase 1 Application Shell Design

**Date:** 2026-08-26
**Base branch:** `origin/dev`
**Base commit:** `df6e771a32f426421bb4b0f78b61594c9dac91a1`
**Feature branch:** `redesign/ui-phase1-app-shell`

## Purpose

Phase 1 turns StockViz from a set of website pages into a coherent financial research and paper-trading workstation. It establishes the product shell, route hierarchy, navigation model, responsive behavior, and semantic visual foundations that later page redesigns will inherit. It does not substantially redesign existing research, portfolio, or trading pages.

Guest access to the existing public research routes is preserved. Markets, stock detail, Screener, Compare, Backtest, Recommendations, News, and Leaderboard use the product shell for both guests and authenticated users. Portfolio, Trade, Orders, Trade history, Watchlist, Settings, and Alerts keep their current authentication requirements.

## Current-State Findings

- The root layout currently wraps every route in the same website header and footer.
- Eleven destinations compete as peers in the desktop header and mobile dropdown.
- Login, signup, marketing, research, and authenticated trading pages share one layout despite having different jobs.
- Research pages commonly use Tailwind's marketing-style `container`, limiting workstation width on larger screens.
- Theme, account, and alert components are reusable; alert polling is already gated by authentication.
- The API already provides real ticker/company-name typeahead through `searchSymbols`, so global search does not need backend work.
- Existing CSS defines only a minimal shadcn token set. Components already refer to semantic values such as popover, secondary, input, and destructive that should be explicitly defined.
- The current `dev` checkout contains unrelated Compare/ticker-picker edits. The isolated worktree prevents this phase from modifying or committing them.

## Approaches Considered

### Chosen: route-group shells with one product information architecture

Move public marketing/authentication pages into a `(public)` group and all product workspaces into a `(product)` group. Nest the current protected routes under `(product)/(authed)`. URLs remain unchanged because route groups do not affect paths. The product shell is shared by guest and authenticated research sessions; authentication continues to protect only personal routes.

This produces explicit layout ownership, removes conditional pathname logic from the root layout, and keeps every research-to-trade navigation transition inside one workstation.

### Rejected: session-conditional root layout

The root layout could call `auth()` and switch between a website header and application shell. This avoids moving routes but makes layout selection depend on both session and pathname, risks showing different structures for the same research URL, and couples global rendering to authentication.

### Rejected: application shell only around the existing `(authed)` group

This is the smallest file change, but Markets, stock research, Screener, Compare, and Backtest would remain website pages. Navigation from Portfolio to Research would leave the application shell, so the product would still feel fragmented.

## Route and Layout Architecture

```text
app/
├─ layout.tsx                    Root document, providers, global skip link
├─ (public)/
│  ├─ layout.tsx                PublicHeader + main + SiteFooter
│  ├─ page.tsx                  Marketing homepage at /
│  ├─ sign-in-required/
│  └─ (auth)/                   /login and /signup
├─ (product)/
│  ├─ layout.tsx                AppShell; no traditional footer
│  ├─ dashboard/                Lightweight workspace entry at /dashboard
│  ├─ markets/
│  ├─ stocks/[ticker]/
│  ├─ screener/
│  ├─ compare/
│  ├─ recommendations/
│  ├─ news/
│  ├─ backtest/
│  ├─ leaderboard/
│  └─ (authed)/                 Existing protected personal routes
│     ├─ portfolio/
│     ├─ watchlist/
│     ├─ trade/
│     ├─ orders/
│     ├─ trades/
│     ├─ settings/
│     └─ alerts/                Actions/API integration retained
├─ api/                         Unchanged route handlers
├─ error.tsx
├─ global-error.tsx
└─ not-found.tsx
```

The root layout remains a server component and owns the HTML document, theme provider, and keyboard skip link. Public and product layouts own their respective landmarks. The product layout reads the session once to enable alerts while preserving server-component defaults. Existing proxy protection remains URL-based and keeps the same protected URLs; the action-only alerts directory does not add a page route.

## Product Shell

### Desktop composition

At `lg` and above, the shell uses a fixed 224px navigation sidebar and a flexible content column. A compact 52px utility bar stays at the top of the content column. The workspace content uses all remaining width, with a maximum safety gutter rather than a marketing container.

```text
┌──────────────────────┬──────────────────────────────────────────────────┐
│ StockViz             │ [ Search ticker or company… ]    alerts theme me │
│ EOD research         ├──────────────────────────────────────────────────┤
│                      │                                                  │
│ Home                 │  current page content                            │
│ Markets              │                                                  │
│ Research             │  existing pages keep their internal composition  │
│   Screener           │  while gaining workstation width and rhythm      │
│   Compare            │                                                  │
│   Recommendations    │                                                  │
│   News               │                                                  │
│ Trade                │                                                  │
│   Trade ticket       │                                                  │
│   Orders             │                                                  │
│   Backtest           │                                                  │
│ Portfolio            │                                                  │
│   Overview           │                                                  │
│   Watchlist          │                                                  │
│   Trade history      │                                                  │
│ Community            │                                                  │
│   Leaderboard        │                                                  │
└──────────────────────┴──────────────────────────────────────────────────┘
```

Top-level domains carry icons and stronger labels. Child routes use indentation, smaller type, and lower contrast. This preserves one-click access without presenting eleven equal-priority choices. The active route uses a slim gold ledger marker and a quiet tonal surface; inactive hover states use neutral surface tokens rather than gold.

Home links to a new `/dashboard` product entry. The dashboard is deliberately lightweight: it orients users to Markets, Research, Trade, Portfolio, and Community and may reuse existing market-mover content. It does not introduce new analytics or redesign downstream pages.

### Navigation state

Route matching is defined in a data-only navigation module and tested independently. Exact and prefix matching identify both the active child and owning domain. Stock-detail routes activate Research while Markets remains a direct discovery destination. Protected links stay visible to guests because existing sign-in redirects communicate availability and preserve callback URLs.

The sidebar does not add a desktop collapse control in Phase 1. At the target widths, a stable 224px information architecture is clearer than a stateful icon-only rail. Collapsed behavior is limited to the responsive mobile transition.

### Utility bar

- A real ticker/company search calls the existing symbol-search endpoint with a short debounce.
- Results expose ticker and company name, support pointer selection, Escape, Arrow Up/Down, and Enter, and navigate to `/stocks/{ticker}`.
- `Ctrl+K` and `Cmd+K` focus the search only if the shortcut hint is shown.
- Existing alert, theme, and account controls are reused and visually normalized to the compact bar.
- No live-market indicator is invented. The sidebar shows a static “EOD data” label because the product genuinely uses end-of-day data.

## Mobile and Responsive Behavior

Below `lg`, the fixed sidebar is removed from layout flow. The utility bar contains a menu trigger that opens an accessible left-side Radix dialog/sheet containing the same navigation hierarchy and reachable account/theme/alert controls. Selecting a route closes the drawer. Focus is trapped while open, Escape closes it, and the trigger exposes its accessible name and open state.

Page content keeps a 16px mobile gutter and may retain intentional horizontal scrolling inside financial tables. The shell prevents document-level horizontal overflow but does not force dense desktop tables into misleading card stacks.

## Public Shell

The public shell retains a calm website header and footer for the marketing homepage, login, signup, and sign-in-required flow. Its navigation is reduced to a few product entry points plus authentication actions; it does not repeat the workstation's full route list. Authenticated visitors receive an “Open workspace” path without forcing the product sidebar onto the marketing page.

## Visual System

### Subject and audience

The subject is an end-of-day equity research and paper-trading instrument for self-directed investors. Its job is to let users move from discovery to investigation, simulated action, and monitoring without losing context. The visual language borrows from ledgers, research terminals, and precision instruments rather than consumer-finance cards.

### Palette plan

The CSS implementation uses OKLCH semantic tokens, with these hex values as visual anchors:

- **Graphite canvas:** `#0C0E12` dark / `#F5F6F8` light
- **Instrument surface:** `#13161C` dark / `#FFFFFF` light
- **Secondary surface:** `#1A1E26` dark / `#ECEFF3` light
- **Brand gold:** `#D3A83F`
- **Positive:** `#2BA477`
- **Negative:** `#D75D63`

Separate semantic tokens cover background, elevated surface, secondary surface, hover surface, card/popover compatibility, border, muted border, input, text hierarchy, focus ring, warning, positive, and negative. Gold is reserved for brand, current navigation, selection, and primary action. Neutral interactions use neutral surfaces; green and red remain semantic.

### Typography plan

- **Interface and headings:** a disciplined system sans stack led by `Segoe UI Variable` on Windows and platform UI sans elsewhere. Weight, tracking, and spacing create hierarchy without adding a network font dependency.
- **Financial data:** the existing platform monospace stack with tabular numerals for prices, quantities, percentages, P&L, and compact status data.
- **Utility labels:** the interface face at 11–12px with restrained letter spacing where it encodes a real category, such as a navigation domain or EOD data status.

### Surface and shape

- The base radius is 6px; controls remain comfortably clickable without becoming pills.
- Dividers and subtle tonal shifts establish most structure.
- Cards remain available for conceptual groups but are not added around existing page sections simply to match the shell.
- Shadows are limited to floating overlays and the mobile drawer.
- Reusable width classes cover workstation/full-width, content, and narrow/form contexts.

### Signature element

The shell's distinctive element is the **ledger spine**: a continuous, disciplined vertical alignment through the brand mark, domain icons, child indentation, and slim gold active marker. It makes the sidebar read like an index to a financial instrument rather than a generic SaaS menu. This is the one expressive device; the rest of the shell stays quiet.

### AI-default self-critique

The first-pass risk was a generic dark SaaS sidebar with rounded active pills and isolated utility-card controls. The revised direction removes pill navigation, avoids gradient accents and decorative dashboard cards, uses a narrow ledger marker for state, and treats density and alignment as the visual identity. It also avoids a new web font because reliability and numeric scanning matter more than novelty in this phase.

## Components and Responsibilities

- `AppShell`: server-owned composition of sidebar, utility bar, and main landmark.
- `app-navigation`: typed domain/route definitions plus pure active-route helpers.
- `AppSidebar`: desktop navigation landmark and brand/data-mode context.
- `MobileNav`: client-only dialog state and responsive navigation rendering.
- `TopUtilityBar`: compact shell row composing search and existing utilities.
- `GlobalTickerSearch`: client-only debounced combobox and keyboard shortcut.
- `PublicHeader`: reduced marketing navigation and authentication entry.
- `PageFrame`: reusable width/gutter variants for future phases and the new dashboard.

The route model and route-matching helpers remain independent of React so navigation behavior is easy to test and reuse between desktop and mobile renderers.

## Data Flow and Failure States

Typing in global search debounces a call to `searchSymbols`. A monotonically increasing request identifier or cancellation guard prevents stale responses from replacing newer results. Blank input performs no request. Loading state is announced without blocking typing. API failure produces a quiet “Search unavailable” result with no fabricated suggestions; subsequent input retries normally. Selecting a valid result navigates directly to the existing stock-detail route.

Alert polling, theme persistence, sign-in, sign-out, and account links retain their current data paths. The shell introduces no new backend calls beyond the existing search endpoint.

## Accessibility

- Preserve the global skip link and make its target the product or public main landmark.
- Use semantic `header`, `nav`, `main`, and `footer` landmarks without duplicates.
- Add `aria-current="page"` to the active destination and meaningful group labels to navigation.
- Provide visible, tokenized `:focus-visible` treatment in both themes.
- Maintain at least 40px mobile utility targets and accessible icon-button labels.
- Implement combobox/listbox keyboard behavior and status announcements.
- Use Radix dialog focus management for mobile navigation.
- Respect `prefers-reduced-motion` for drawer/overlay and existing transition utilities.

## Test Strategy

Implementation follows red-green-refactor for new behavior.

### Unit/component tests

- Navigation helpers map every product route to the correct domain and active child.
- Desktop and mobile navigation expose the same destinations with correct `aria-current` state.
- Mobile drawer opens, closes with Escape, and closes after navigation.
- Global ticker search skips blank queries, debounces input, handles stale/error results, supports keyboard selection, and navigates to the selected stock.
- Public and product layout components expose the expected landmarks and omit the product footer.

### Existing quality gates

- `pnpm lint`
- `pnpm typecheck`
- `pnpm --filter @stockviz/web test`
- `uv --directory apps/api run pytest`
- `pnpm build`
- Playwright e2e when the database/API prerequisites are available

### Visual QA

When browser access is available, inspect `/`, `/login`, `/markets`, `/stocks/AAPL`, `/screener`, `/portfolio`, `/trade`, and `/backtest` at approximately 1440px, 1280px, and mobile width in both themes. Capture desktop and mobile screenshots and fix shell-level overflow, active-state, contrast, spacing, and footer issues. The current session exposes no connected browser, so screenshot capture may be unavailable; command-line Playwright remains conditional on its documented API/database prerequisites.

## Scope Boundaries

- No backend or API behavior changes.
- No substantial redesign of stock detail, Portfolio, Markets, Screener, Backtest, Trade, Compare, or Recommendations.
- No chart implementation changes.
- No email/push alerts, live quotes, command palette, or expanded dashboard analytics.
- No new large dependency; existing React, Tailwind, shadcn/Radix, Lucide, and Next.js facilities are sufficient.

## Completion Criteria

Phase 1 is complete when route ownership is cleanly split, every product route renders inside the workstation shell, the public flows retain a suitable website shell, product pages have no conventional footer, navigation hierarchy and states are accessible, real ticker search works, semantic tokens are available in both themes, mobile navigation works, existing route behavior is preserved, and the relevant quality gates pass.
