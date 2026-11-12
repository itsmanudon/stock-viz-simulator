# apps/web — agent guide

Next.js 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui, NextAuth v5.

## Layout

```
app/
  (public)/        marketing home, /product/[slug], login, signup, sign-in-required; owns the
                   concise public header and traditional website footer
  (product)/       guest-capable research routes plus the workstation shell
    (authed)/      dashboard, portfolio, trade, trades, orders, watchlist,
                   alerts, settings, earnings — protected by proxy.ts. `/dashboard` is
                   the signed-in home: a bento grid of portfolio widgets fed by
                   `lib/dashboard-data.ts` (every widget but the portfolio hero
                   degrades to its own empty state if its request fails).
                   Portfolio and trade show reserved
                   vs available cash/shares from pending orders. `/trade` is
                   the execution workstation; `/stocks/[ticker]` keeps the
                   contextual ticket. `/alerts` is alert management; the header
                   bell is compact status. Operational prices (close, trigger,
                   fill, alert target) format in the symbol-native currency.
  api/auth/        NextAuth handler
  markets/         sortable symbol table
  stocks/[ticker]/ chart + indicators + news + comments + sentiment + simulated quote badge
  compare/         Research workspace: normalized multi-ticker comparison
  screener/        filterable symbol screener
  backtest/        Research workspace: strategy experiment + equity curve
  recommendations/ Research workspace titled Signals (route unchanged)
  leaderboard/     user NAV ranking
  news/
  sign-in-required/  redirect target for unauthenticated access
  layout.tsx       document providers + skip link only; route groups own chrome
auth.ts            NextAuth v5 setup (credentials provider, bcrypt)
auth.config.ts     Edge-safe config (no node-only imports)
proxy.ts           NextAuth middleware
components/
  dashboard/       signed-in home widgets (hero, movers, orders, alerts,
                   watchlist, allocation) + the shared WidgetCard/DeltaPill
  marketing/       public-page-only pieces. `hero.tsx` (server: centred copy,
                   pill CTAs, chips; hands everything to `hero-stage.tsx`) +
                   `hero-stage.tsx` (client: the real-data panel with a phone
                   in front that rotates through `hero-phone-screens.tsx`; on
                   `lg` with motion the hero pins from the first scroll, rises
                   into view inside the same timeline (a negative wrapper margin
                   closes the gap the rise leaves), and the paper card lifts out
                   of the phone, then flips; elsewhere the same copy is a plain
                   section. Card start is measured from layout offsets because
                   ScrollTrigger re-measures mid-timeline) +
                   `hero-phone-screens.tsx` (portfolio is a labelled example;
                   stock/review use the real stored close and date; news shows
                   source and date only and is skipped when empty) +
                   `hero-panel.tsx` (the
                   `.panel-inset` product replica, real bars only, aria-hidden),
                   `phone-frame.tsx` (the shared phone bezel; screens never
                   shrink), `landing-sections.tsx` (server sections below the
                   hero: movers dated per card, session tiles, scroll story
                   wrapper, fill steps, statement band, public-only rankings,
                   FAQ; each drops out when its data is missing),
                   `scroll-story.tsx` (client: sticky phone follows the step in
                   view; `overflow-x-clip`, never `hidden`, or sticky breaks),
                   `landing-motion.tsx` (client: one GSAP pass over
                   `data-motion` markers — words, rise, draw, count, steps,
                   glow), `product-page.tsx` (`PRODUCT_PAGES`: the specs
                   behind `/product/[slug]` — paper-trading, research,
                   replay; facts are checked against shipped behaviour, and
                   there is no news page until Aegis lands; the public header
                   links these three). `market-ticker`, `product-tour`/`tour-*` and
                   `by-the-numbers` are no longer on the home page (kept for
                   now, unused),
                   `market-ticker.tsx` (the `.marquee` price strip — halves are
                   `min-w-[100vw]`, never `min-w-full`, see the file header),
                   `floating-header.tsx` (the public header's sticky pill; the
                   only client part — it flips `data-scrolled` past 24px and
                   everything inside stays server-rendered), `market-status.tsx`
                   (latest stored EOD bar date; never claims a live market),
                   `product-tour.tsx` + `tour-tabs.tsx` + `tour-panels.tsx`
                   (the tabbed Screen/Research/Simulate/Track tour — panels are
                   live recreations off the public API, never screenshots; a
                   surface that fails is dropped, <2 tabs hides the section),
                   `by-the-numbers.tsx` (counts read live off the API; a stat
                   that can't be counted is omitted, never shown as 0),
                   `proofs/` ("Watch it work", motion batch 1: `proof-section.tsx`
                   loads real data server-side and renders one row per feature,
                   each with its own client animation: `ghost-runs.tsx`
                   (backtest curve among 36 bootstrap reshuffles of its own
                   daily returns), `sieve.tsx` (screener chips through
                   cumulative real screener queries), `fog-replay.tsx` (stored
                   closes, future under fog), `print-stamp.tsx` (example order
                   priced at a real stored close). All run on `useFrameLoop`
                   in `canvas-loop.ts`: draw is a pure function of time, runs
                   only on screen, paints the final frame under reduced motion.
                   Canvases are aria-hidden; each row states its figures in
                   text. The landing shows all four; /product pages pick theirs
                   with `only`. No GSAP inside them. Batch 2 adds
                   `rebase-snap.tsx` (compare: two symbols spring onto one
                   index; a US/India pair, else a same-currency fallback, and
                   the copy says which), `sonar-sweep.tsx` (signals: distance
                   from the centre is the vote share) and
                   `liquid-allocation.tsx` (an example account's split at two
                   real closes, SVG goo), on /product/research and
                   /product/paper-trading; and `departure-board.tsx`, the
                   split-flap board in the landing Rankings section, which
                   keeps an sr-only list of the same rows. Batch 3 adds
                   `market-weather.tsx` (faint aurora behind the hero and
                   closing CTA, coloured by `breadth.ts`: share of symbols that
                   closed up; the hero chips and the CTA state the figure),
                   `decode-text.tsx` (Moving today figures resolve digit by
                   digit; sr-only real text), `exploded-candle.tsx` (one stored
                   bar taken apart beside the FAQ) and `loupe-chart.tsx` (the
                   "chart" row on /product/research: a magnifier that reads a
                   day's OHLC)),
                   `closing-cta.tsx` (the monochrome full-bleed close),
                   `reveal.tsx` (scroll reveal: IntersectionObserver + the
                   `[data-reveal]` transition in globals.css). GSAP (+
                   ScrollTrigger, SplitText, `@gsap/react`) is allowed on
                   marketing pages only, never in the product app. Wrap every
                   animation in `gsap.matchMedia("(prefers-reduced-motion:
                   no-preference)")`, never hide content before GSAP runs, and
                   pin a section only inside a React-owned wrapper
  data-table.tsx   DataTableFrame / NumericCell / SortableHead / TableToolbar
  symbol-card-list.tsx  card layout the symbol tables switch to under `md`,
                   plus CardSortBar (cards have no column headers to sort by)
  page-header.tsx  PageHeader / PageSubnav / PageEmptyState — the single
                   implementation behind the Operational* and Research* wrappers
                   (+ MetaChip, the rounded date/zone chip for a header's meta row)
  figure-strip.tsx FigureStrip: a row of headline figures in one bordered strip
                   (Aurora board v3); /markets breadth and /backtest results use it
  range-bar.tsx    RangeBar + rangePositionPct: a price's place in a range as a
                   marker on a monochrome track (screener 52-week, compare)
  strength-dots.tsx StrengthDots: one dot per signal vote plus the count
                   (`dotsFrom="md"` keeps phone rows wide enough for names)
  count-badge.tsx  CountBadge: the rounded count beside a tab label (Portfolio
                   tabs; reuse for any tab that counts its rows)
  status-badge.tsx one tone-mapped chip behind the order/alert badges
  order-side-toggle.tsx  buy/sell segmented control shared by both tickets
  ui/              shadcn-generated primitives — don't hand-edit
  site-footer.tsx  public footer: rides `.panel-inset` squared off, so the page
                   ends dark; disclosures are numbered notes, not buried prose
  *.tsx            app-shell/sidebar/navigation, global-ticker-search, earnings-calendar,
                   public-header, price-chart, order-ticket, backtest-form, etc.
lib/
  api/             fetch client for FastAPI, one module per resource
                   (client.ts = public, server.ts = authed, types.ts = shared types)
  db.ts            raw pg pool (only used by the credentials provider)
  users.ts         user lookup/create for credentials auth
  utils.ts         cn() helper
tests/e2e/         Playwright specs (shell, auth, markets, trade, marketing).
                   `marketing.spec.ts` covers the public home: tour tabs and
                   keyboard nav, reduced motion (via `page.emulateMedia` — the
                   `reducedMotion` fixture did not reach the page), both themes,
                   and horizontal overflow at 320-1440. Keep 1024/1280/1366 in
                   that width list: the hero's cropped panel broke only there.
tests/unit/        Vitest (shell/navigation/search, csv, tables, guards, rate-limit)
types/next-auth.d.ts  augments Session.user with id
sentry.*.config.ts    Sentry init per runtime; no-op without DSN
instrumentation.ts    Next 15+ hook that loads the right sentry config
Dockerfile            Production standalone image; build from the **repo root**
next.config.ts        `output: "standalone"` + `outputFileTracingRoot` at repo root
```

## Two API clients — pick the right one

- `lib/api/client.ts` → `apiGet<T>(path)` — **public** endpoints, callable from
  server components or the browser. No auth header.
- `lib/api/server.ts` → `authedGet/authedPost` — **server-only**, marked with
  `import "server-only"` so it can't accidentally leak into a client bundle.
  Reads `auth()`, mints a short-lived HS256 JWT (`jose`, `{ sub: user.id }`,
  60 s expiry) signed with `INTERNAL_API_TOKEN`, and sends it as
  `Authorization: Bearer <token>`. Use for anything that reads or mutates
  per-user data (`/v1/portfolio`, `/v1/trades`, `/v1/orders`, `/v1/options`,
  `/v1/watchlist`, `/v1/alerts`, ...).

If you need an authenticated call from a client component, route it through
a server action or a route handler — never through the browser.

## NextAuth specifics

- v5 beta. `auth()` is the server-side session reader; use it in server
  components and `authedFetch`.
- Providers: **Credentials** (email + password, bcrypt) and **Google OAuth**
  (needs `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`; see `.env.example`).
- Google signs in only to an account Google created, for an address Google
  verified (`signIn` callback in `auth.ts`, rule in `lib/oauth-linking.ts`;
  audit OP-4). Sign-up does not verify email, so an account with a password
  never gets Google attached: its holder signs in with the password, and
  `/login?error=` explains the refusal.
- Credential sign-in and sign-up are throttled by fixed windows in Postgres
  (`lib/rate-limit.ts`, table `auth_rate_limits` owned by the API's Alembic
  chain; audit OP-8), so counters survive the web service sleeping. A
  successful sign-in clears the email's counter only, never the address's.
- The API does not rate-limit the web server's own calls (audit RS-6):
  `lib/api/client.ts` adds `X-StockViz-Web` on the server, from the key
  `instrumentation.ts` registers (`lib/web-server-key.ts`; never in the
  browser bundle). Instead `/screener`, `/compare` and `/stocks/[ticker]`
  call `checkVisitorLimit()` (`lib/visitor-limit.ts`) first: 30, 30 and 60
  views a minute per visitor address, in the same `auth_rate_limits`
  counters, failing open. A new query-driven public page should do the same.
- Sessions are JWT (default). The user.id is persisted via the `jwt` callback
  and surfaced via the `session` callback (see `auth.ts`).
- `proxy.ts` runs as Edge middleware. Keep node-only imports out of the files
  it transitively imports (that's why `auth.config.ts` is split from `auth.ts`).

## Build/run

```powershell
pnpm dev:web              # turbopack dev server on :3000 (or :3001)
pnpm --filter @stockviz/web build
pnpm --filter @stockviz/web lint     # biome
pnpm --filter @stockviz/web typecheck
```

The build runs `next build` with Turbopack. If `SENTRY_AUTH_TOKEN` is set,
`withSentryConfig` uploads source maps; otherwise it's a plain build.

`next.config.ts` sets `output: "standalone"` so `apps/web/Dockerfile` can
copy `.next/standalone` into a slim Node image (`CMD node apps/web/server.js`).
Build from the repository root:

```powershell
docker build -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t stockviz-web:dev .
```

`NEXT_PUBLIC_API_URL` is inlined into the **browser** bundle at image build.
For kind port-forward it must be a URL the laptop can reach (typically
`http://localhost:8000`). Cluster DNS such as `http://stockviz-api:8000` is
not reachable from the browser. Server-side fetches use runtime `API_URL`
(the web Deployment sets `http://stockviz-api:8000`).

Kubernetes overwrites `HOSTNAME` with the pod name. The image `CMD` exports
`HOSTNAME=0.0.0.0` before `node apps/web/server.js` so the process listens on
all interfaces. Probes use `GET /api/health` (no SSR), not the homepage.

The image `pnpm install` uses `node-linker=hoisted` so Next standalone tracing
can copy `@swc/helpers`. Isolated pnpm (the local default) omits that package
and the container crashes with `MODULE_NOT_FOUND`.

## E2E (Playwright)

```powershell
pnpm e2e                  # or: pnpm --filter @stockviz/web e2e / e2e:ui
```

Specs live in `tests/e2e/`. The Playwright `webServer` runs `pnpm start`
(production mode), so you need a build first plus the API on :8000 against a
migrated + seeded DB. Full local sequence from the repo root:

```powershell
$env:INTERNAL_API_TOKEN = "local-e2e-token"   # not the committed dev default
$env:AUTH_SECRET = "local-e2e-secret"         # not the committed dev default
$env:AUTH_TRUST_HOST = "true"         # prod builds don't trust the host by default
pnpm db:up && pnpm api:migrate
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill
uv --directory apps/api run python -m stockviz.cli recommend
pnpm api:dev                          # another terminal, same INTERNAL_API_TOKEN
pnpm --filter @stockviz/web build
pnpm e2e
```

The committed dev defaults do **not** work here. `pnpm start` runs with
`NODE_ENV=production`, and `lib/env.ts` refuses the published defaults for
`INTERNAL_API_TOKEN` and `AUTH_SECRET`: the server never becomes ready and
Playwright times out after 60 s. Set both to any other value in the
environment (it overrides `.env.local`), and give the API the same
`INTERNAL_API_TOKEN`. CI does this with its own values, see the `e2e` job in
`.github/workflows/ci.yml`. If a `pnpm dev` server is already on :3000,
Playwright reuses it and the dev defaults are accepted. Runs single-worker,
chromium only.

`pnpm start` (`next start`) warns under `output: standalone` and can duplicate
the page tree. Scope product assertions to `#main` rather than matching the
whole document.

## Sentry

`instrumentation.ts` → `sentry.server.config.ts` (Node) or `sentry.edge.config.ts`
(Edge). `instrumentation-client.ts` → browser. All three early-return if their
DSN env var is empty, so `pnpm dev`/`pnpm build` work offline.

## Conventions

- shadcn components go in `components/ui/`. To add one: `pnpm dlx shadcn@latest add <name>`.
- Use Tailwind utilities; the palette lives in `app/globals.css` as CSS
  variables. The identity is **Aurora** (design board in the workspace repo at
  `docs/design/2026-11-11-aurora-direction/`): navy-biased neutrals, a cool
  light canvas (`#f4f6fa`) and a navy-black dark canvas (`#06080f`, the
  default theme), 10px radius (`--radius: 0.625rem`), Geist display + Geist
  Mono numerals (both self-hosted via `next/font`, no runtime request).
  `--brand` is aqua in dark and blue in light (aqua fails contrast on white)
  and is reserved for identity, focus, and selected controls. The
  `--brand-gradient-from/via/to` stops and `--marketing-glow` feed the brand
  primitives in globals.css — `.paper-card` (`components/paper-card.tsx`),
  `.brand-glow`, `.glass` — which belong to brand moments only (the dashboard
  hero, public pages, onboarding), never behind a chart, table, ticket or a
  gain/loss figure. `.figure-minor` dims the cents of a headline amount; split
  it with `splitMinorUnits()`. Positive is a separate green (`--positive`) and negative
  a separate red. `--*-soft` / `--*-soft-foreground` pairs
  (positive/negative/warning/neutral) are the tinted fills behind delta and
  status pills — use `DeltaPill` rather than re-rolling the chip.
  `--surface-elevated` is one step *above* `--card` (overlays: sidebar,
  popovers, sheets); `--card` is for content tiles sitting on the page.
- **Type** (owner's pick, 12 Nov 2026): Geist for all text, including every
  ticker symbol (the `ticker` utility in globals.css, paired with
  `font-semibold`); Geist Mono only for figures (prices, quantities, deltas)
  so columns line up. Product page titles are Geist 600 with
  `tracking-[-0.025em]`, like the stock page's company name; marketing
  headlines stay 500. Geist Mono draws its own ₹ (its `latin-ext` subset is
  loaded), so there is no ₹ fallback face any more.
- **Dark only for now** (owner, 12 Nov 2026): `components/providers.tsx`
  sets `forcedTheme="dark"`, and the theme toggles are gone from the top bar,
  the public header, the footer and Settings. The light tokens stay in
  `globals.css` and `theme-toggle.tsx` stays in the tree, so the light theme
  can return after its own design pass. Don't design new screens light-first.
- The type ramp adds `text-3xs` (10px) and `text-2xs` (11px) below Tailwind's
  `text-xs` for dense table meta and column labels. Use them instead of
  arbitrary `text-[10px]` / `text-[11px]`, which bypass the scale.
- `--muted-foreground` is an **alias** of `--text-secondary`, so the shadcn
  vocabulary and the app's `text-secondary`/`text-tertiary` pair render
  identically. Prefer the semantic names in app code; `text-muted-foreground`
  stays only because `components/ui/` is generated against it.
- Symbol tables are ~500px+ wide at their narrowest, so `/markets` and
  `/screener` render `SymbolCardList` under `md` and the table above it. Both
  branches carry the same figures — mobile re-lays them out rather than
  dropping columns. Any new symbol table should do the same. `/orders`,
  `/watchlist` and `/alerts` follow it too (cards under `md`, table above;
  `OrderCard` lives beside `OrderBlotterRow`), and operational times render
  in UTC with the zone named. Sector and exchange come from `stockviz.cli
  metadata`, which needs network: a table leaves out a Sector or Exchange
  column that no row has a value for, and the stock page says "Not recorded"
  (UI audit S3).
- Tables: use `DataTableFrame` + `NumericCell` rather than hand-rolling the
  bordered wrapper and the right-aligned tinted number. `NumericCell` owns the
  sign→token mapping and the em-dash fallback — never write `text-green-500`
  or `text-red-500`, which are not the `--positive`/`--negative` tokens.
- The stock page chart draws RSI in its own pane with 70/30 guides (#73),
  beside MACD; indicator values come warmed up from the API (Phase 6.1), so
  they do not change with the timeframe. The change pill is labelled
  "<tf> return since <first bar>" (UX-10).
- Chart indicators come from the API registry (Phase 6.6): `STOCK_INDICATORS`
  in `lib/stock-workspace.ts` lists names with a menu `section`, and
  `chartLayers()` splits the bundle by each indicator's `meta.pane`: price
  overlays (Supertrend's `.direction` output is left out) and one small
  `IndicatorPane` per separate-pane indicator under the chart. RSI and MACD
  keep their own panes. A new indicator needs only a menu entry.
- `POST /api/revalidate` (audit RS-9, Phase 6.6) is called by the nightly
  cron's last step with `x-stockviz-revalidate` (HMAC of a fixed label under
  `INTERNAL_API_TOKEN`, `lib/revalidate-key.ts`) and drops every tag in
  `MARKET_TAGS` with `revalidateTag(tag, { expire: 0 })`, so a page never
  mixes two nights. `getSymbol` (tags `bars`, `symbols`) and `getIndicators`
  (`bars`) are cached an hour with the bars they sit beside. A new cached
  market-data fetch should carry one of those tags.
- `/watchlist` draws sparklines from each row's `closes` (RS-12, one API
  call instead of one per item), and the add form is a searchable input with
  a datalist of symbols (UX-7), nothing preselected.
- The stock page's Financials tab (`components/fundamentals-panel.tsx`,
  Phase 6.4) shows key multiples as of today with their reasons when null,
  the P/E percentile over five years of month-ends, and annual/quarterly
  statements labelled by period end and unit. It says when figures are not
  point-in-time (yfinance) and when the reporting currency differs from the
  trading currency. A failed financials call hides the panel, not the page.
- Charts use `lightweight-charts` v5. The wrapper lives in
  `components/price-chart.tsx`; reuse it rather than instantiating a chart inline.
  Compare and backtest charts live in `compare-chart.tsx` and `equity-curve.tsx`.
  Canvas can't read CSS vars, so all three take their colours from
  `useChartPalette()` (`lib/chart-theme.ts`), which reads the tokens off the
  document and re-reads on theme change — never hard-code chart colours. The
  hook keeps its object identity stable while colours are unchanged because
  callers pass it to `useEffect`, and a new identity forces a full chart
  rebuild. Fit the time axis with `fitWithLabelRoom()` (`lib/chart-range.ts`),
  not `timeScale().fitContent()`: it leaves room for the outermost date label,
  which lightweight-charts otherwise clips ("ug", "25"; UI audit P4). A volume
  series on the price pane sets `lastValueVisible: false` and
  `priceLineVisible: false`, or its tag sits on the price labels.
- Server components by default — only mark `"use client"` when you need state,
  effects, or interactivity.
- Research (`/compare`, `/backtest`, `/recommendations`, `/replay`) is one
  domain. See [`docs/RESEARCH.md`](../../docs/RESEARCH.md). Keep URL state
  shareable (`tickers`/`tf`, `ticker`, `min`/`signal`/`q`). Do not present
  Signals as AI advice; the engine is a seven-vote rule set. Replay Lab is
  future-blind historical simulation; never fetch live bars, SSE quotes, or
  news into `/replay/[id]`. Forensics (`?view=forensics`) may call session
  `/forensics`, `/journal`, `/history`, `/summary`, and `/fills` only.
- `/backtest` starts on the first symbol with stored closes and ends its
  range at that symbol's latest close (`lib/backtest-defaults.ts`, UI audit
  F1), using `last_close_at` from the markets summary. The range follows the
  chosen symbol until the dates are edited by hand. The run is a browser
  call to the API, so a dev server on a port other than 3000 needs that
  origin in the API's `CORS_ORIGINS`, or the run fails with "Failed to fetch".
- `/backtest` (Phase 5.2-5.4) sends `fill_rule` (default `next_open`),
  `spread_bps`, `fee_schedule` and `return_mode`, formats amounts in the
  run's `currency`, and states the basis, return mode, warm-up and profile
  under the results. "Save run" (`components/backtest-run-actions.tsx`, server
  action in `app/(product)/backtest/actions.ts`) stores the request through
  `/v1/experiments/runs`; `/backtest/runs` (protected in `proxy.ts`) lists
  saved runs with a Rerun check (identical, different, or data changed).
  Beside Save run, "Walk-forward" and "Sweep settings" (Phase 5.5) run the
  default grid on the server and store the study; `/backtest/runs/[runId]`
  shows a walk-forward's windows (chosen setting, scored year) or a sweep's
  ranked settings ("best of N").
- The `/trade` option ticket (`components/option-trade-form.tsx`) quotes
  before it buys (audit LG-7): `getOptionQuote()` (`lib/api/option-quote.ts`,
  a browser call to the public `/v1/options/quote`) shows spot with its close
  date, volatility, value per share and premium, and the buy button names the
  premium. The strike starts at the money and follows the symbol until edited.
  Only USD symbols are offered. `PortfolioMetrics` adds an "Other cash" figure
  when `cash_by_currency` (Phase 4.5b) holds a non-base currency: a sale of a
  EUR stock keeps its euros. The portfolio header and the dashboard hero
  show `ValuationNotice` when `valuation_warnings` is not empty (audit LG-13).
- Operational trading (`/trade`, `/orders`, `/watchlist`, `/alerts`) is the
  authenticated execution/monitoring loop. See
  [`docs/OPERATIONAL_TRADING.md`](../../docs/OPERATIONAL_TRADING.md).
  `/trade?ticker=` prefills the ticket. `/orders?status=` is URL-backed.
  Do not describe EOD fills or alert evaluation as live exchange execution.
- Both paper tickets are two-step (UI audit UX-4): the stock page's
  `ContextualTradeTicket` and the `/trade` `OrderTicket` ("Review market buy"
  then "Place market buy") open the shared `OrderReview` from
  `components/order-review.tsx` (amount, reference close with its date, fees,
  fill rule from `describeFillRule()`, buying power after) and only the
  review's button submits; the shared `OrderConfirmation` replaces the form
  after success. The Replay ticket is separate and still single-step.
  Server actions post without JavaScript, so the ticket sends
  `review_step=draft|confirmed` and `placeTradeAction`/`placeOrderAction`
  refuse a `draft` post (`lib/order-review.ts`); the review button also stays
  disabled until hydration (`useHydrated()`). Tickets that omit the field
  (Replay) are unaffected. Below `xl`, `MobileTradeSheet` pins a Buy/Sell bar to the bottom
  of the viewport; the page adds `pb-32` so it never covers content.
- A `"use server"` file may export only async functions (and types). Put
  constants and helpers that actions share in `lib/`, or Next refuses the module.
- Every displayed price names its close: `/v1/markets/summary` rows carry
  `last_close_at`, screener rows `as_of` and watchlist rows `last_close_at`
  (UI audit T1, audit RS-13). The summary's `change_pct` is null when the last
  two bars are more than five days apart or the row's close trails the newest
  close on the page by more than five days, so a stalled symbol never shows an
  old move as today's. Symbols end
  on different days, so date each row, not the page. In `next dev`, responses
  fetched with `revalidateSeconds` live in `.next/dev/cache/fetch-cache` (not
  `.next/cache`) and survive restarts; clear that folder after an API schema
  change or the page keeps the old shape. The production image copies only
  `.next/standalone`, `static` and `public`, so each deploy starts with an
  empty data cache; the cache then holds a response for up to its revalidate
  window (an hour for market data), so a page can trail the nightly ingest by
  that long. Still render new fields optionally.
- `/screener` reads `/v1/screener` (Phase 6.2): filtered, sorted and paged
  on the server (50 a page, `?page=`), with market, currency, trend (close vs
  SMA 50/200) and volatility filters, Market and "vs 200-day" columns, and
  saved screens for signed-in users (`components/saved-screens.tsx`, actions
  in `app/(product)/screener/actions.ts`; a saved screen is the URL query).
  Any filter or sort change goes back to page 1. Phase 6.5 adds a
  Fundamentals filter group (max P/E, min yield, min market cap in USD bn,
  min ROE, max debt/equity), P/E and USD market-cap columns, and row
  checkboxes in a GET form to `/compare` (`?tickers=A&tickers=B`;
  `ClickableRow` ignores clicks on controls inside it). `/compare` cuts every
  series to the days all symbols traded (`alignToSharedDates`, audit RS-7)
  and shows fundamentals side by side (`components/compare-fundamentals.tsx`,
  market cap in each company's reporting currency).
- `/screener` keeps filters and sort in the URL (`lib/screener-view.ts`, UI
  audit UX-1). Each applied filter shows as a removable chip; RSI bounds share
  a chip, and the momentum bounds belong to the window's chip because the API
  ignores them without one. Removing a chip keeps the sort, sorting keeps the
  filters, and the form carries `sort`/`dir` as hidden fields. A momentum sort
  is only valid while a window is set.
- Format stored bar timestamps with `formatCloseDate()` (`lib/stock-workspace.ts`):
  it reads the calendar date from the string, so it never shifts a day with the
  timezone, and always includes the year.
- Never parse an API timestamp with `new Date(iso)`. The API sends UTC with no
  zone ("2025-04-04T00:00:00"), which `new Date()` reads as local time, so east
  of UTC chart bars landed a day early and "UTC" fill times were off by the
  offset (audit RS-2). Use `parseApiTimestamp()` / `barTimeToUtcSeconds()` from
  `lib/api-time.ts`; chart wrappers already do. Test date code under
  `TZ=Asia/Tokyo` as well as UTC.
- The product sidebar follows the Aurora board v3 (`lib/app-navigation.ts`):
  Home, Markets and Earnings, then labelled sections (Research, Trade,
  Portfolio, Community) whose headings are not links but light up while one
  of their routes is open, including `/stocks/*` for Research. Settings sits
  apart at the bottom and only for signed-in users (proxy.ts guards it). The
  wordmark carries the `EOD · SIMULATED` tag, and the top bar shows
  `DataDateChip` (`components/marketing/market-status.tsx`), the newest stored
  bar's date. It is an async server component, so unit tests that render the
  shell mock that module.
- `/dashboard` (Aurora board v3): the hero takes the full width, then
  orders, watchlist and alerts, then movers and allocation. The hero adds the
  last session's move beside the period change once there are three
  snapshots (with two it would repeat the period). The orders widget prices
  triggers in the symbol's currency, from the positions and watchlist the page
  already loads, falling back to USD as `/orders` does.
- The one animation inside the product app is `SettleSweep`
  (`components/settle-sweep.tsx`, motion batch 3): on /orders, an order this
  browser last saw pending that is now filled gets one band of light across
  its status chip (CSS in globals.css, motion allowed only). Last-seen
  statuses live in localStorage under `stockviz:order-status`; the page
  renders each order twice, so both copies compare against one snapshot.
  Keep the rest of the product app still.
- Trading pages (Aurora board v3): `OrderSideBadge` is neutral (an arrow and
  the word), `StatusBadge` carries a leading dot and a `warning` tone, and
  pending orders use it (brand stays for identity and selected controls).
  `/orders` fetches every order once so each status tab shows a
  `CountBadge`. `/trades` prices each row in the trade's own currency
  (`total_native`), times it in UTC with `formatUtcDateTime()`
  (`lib/api-time.ts`), and totals only realized P&L, in the account's base currency. `/trade` keeps chart and recent fills on the left and the ticket and
  account on the right; below `xl` the column wrappers are `contents` and
  `order-*` sets chart, ticket, account, fills. Realized P&L is in the
  account's base currency (`trade.base_currency`, Phase 4.8), and the
  portfolio's NAV change and the journal use it too (`base_currency`,
  journal `currency`). Settings has an "Account currency" panel that restarts
  a fresh account in INR (₹1 crore) or USD (`putBaseCurrency`); once
  `base_currency_locked` it only states the currency.
- Monitoring and Replay (Aurora board v3): watchlist rows act through four
  round icon buttons (research, trade, alert, remove), each with a spoken name
  and a title; `/alerts` view tabs count with the same `matchesView()` rule
  as the list, and an armed alert's badge is neutral. A replay session states
  the blind rule in a banner above everything, dates itself with a
  `MetaChip`, and puts a completed run's summary on `FigureStrip`.
- Compare series differ by line style as well as colour: `seriesDash()` in
  `lib/compare-workspace.ts` cycles solid, dashed, dotted, and both the chart
  and its legend read it. Buy and sell labels stay neutral (an arrow and the
  word), because the side of a trade is not a gain or a loss.
- `/earnings` weeks run Monday to Sunday, and the page fetches exactly
  `viewRange()` from `earnings-calendar.tsx`, so the grid and the request
  can't disagree. Calendar cells are UTC dates: read them with UTC getters.
  `/markets` breadth (`marketBreadth()` in `lib/markets-table.ts`) counts only
  rows with a `change_pct`, so a stalled symbol never enters it.
- News comes from Aegis since Phase 2: `NewsArticle` has a string `id`,
  `tickers`, `available_at`, an optional `url` and `published_at`, and no
  summary or image. Date a headline with `newsDateLabel()`
  (`components/news-list.tsx`): the publisher's date, else "Collected <date>"
  (GDELT sends none, audit AG-12). Signals print `row.maxScore`, not a fixed
  7: the sentiment vote is unavailable without scored news (audit SR-9).
  News for a set of symbols is one call, `getNewsForTickers()` (`/v1/news?tickers=`):
  `/watchlist` lists it under the table, and `/portfolio?tab=news` loads it
  for the holdings only while that tab is open, as Journal does.
- Alerts and notifications (Phase 7.3): `/alerts` lists rules of every kind
  (price level, daily move, technical crossing, Aegis news, portfolio) with
  the rule in words (`description`), the current close and its date from the
  markets summary, the distance to a price target, status (paused, fired,
  dismissed) and when it last fired; actions dismiss, re-arm, pause/resume,
  delete; `?rule=<id>#history` narrows the firing history. `AlertForm`
  (`components/alert-form.tsx`, UX-2) searches symbols with a datalist, shows
  the stored close with its date and the distance to the target, and
  previews the rule (`previewRule` in `lib/alert-rules.ts`). The header bell
  (`components/alerts-bell.tsx`) polls `/api/notifications` (unread count +
  five newest) every 60 s; RS-11: a failed poll keeps the last count and says
  so in its title, and polling stops while the tab is hidden.
  `/notifications` (protected) lists everything by category with paging and
  mark read / mark all read. In-app only.
- `/news-reactions` (Phase 7.4, Research subnav, public, 20 views a minute
  per visitor): an event study from the URL (`tickers`, `sentiment`,
  `event_type`, `pre`, `post`) through `getEventStudy()` (`lib/api/research.ts`,
  cached with `bars`/`news` tags), shown by `components/event-study-view.tsx`
  (windows table, mean CAR path as inline SVG, the events; counts only below
  the minimum; "association, not cause"). The stock page's News tab adds a
  "News reactions" block for its negative and positive news (`NewsReactions`).
- Watchlist rows carry `last_close_at` and `currency`, and alert rows carry
  `currency` (audit RS-13), so the dashboard no longer loads the symbol list
  to format them. `/alerts` still loads it for the create form.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
