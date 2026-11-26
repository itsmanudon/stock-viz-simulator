# apps/web — agent guide

Next.js 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui, NextAuth v5.

## Layout

```
app/
  (public)/        marketing home, /product/[slug], login, signup, sign-in-required; owns the
                   concise public header and traditional website footer
  (product)/       guest-capable research routes plus the workstation shell
    (authed)/      dashboard, portfolio, trade, trades, orders, watchlist,
                   alerts, settings, earnings, setups, replay, drills (A4.7) —
                   protected by proxy.ts. `/dashboard` is
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
  stocks/[ticker]/ chart + indicators + news + financials + position & orders (latest close with its date)
  compare/         Research workspace: normalized multi-ticker comparison
  screener/        filterable symbol screener
  backtest/        Research workspace: strategy experiment + equity curve
  checklist/       Research workspace: the six-dimension Checklist (A2.4; replaced
                   Signals, and `/recommendations` permanently redirects here)
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
                   the copy says which), `sonar-sweep.tsx` (checklist: distance
                   from the centre is the share of the six dimensions met, real
                   `/v1/checklist` rows) and
                   `liquid-allocation.tsx` (an example account's split at two
                   real closes, SVG goo), on /product/research and
                   /product/paper-trading (the landing Rankings section and its
                   `departure-board.tsx` went with the leaderboard in A0).
                   Batch 3 adds
                   `market-weather.tsx` (faint aurora coloured by `breadth.ts`;
                   unused since the PRISM redesign put a WebGL light (now
                   `prism/liquid-chrome.tsx`) behind the hero and closing
                   CTA, which carries the same breadth lean; the hero chips and the CTA state the figure),
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
  strength-dots.tsx StrengthDots: a count out of a fixed number as dots plus
                   "n/max" (the Checklist's dimensions met of six; the dots are
                   aria-hidden, so callers also state the count in words)
  count-badge.tsx  CountBadge: the rounded count beside a tab label (Portfolio
                   tabs; reuse for any tab that counts its rows)
  status-badge.tsx one tone-mapped chip behind the order/alert badges
  order-side-toggle.tsx  buy/sell segmented control shared by both tickets
  ui/              shadcn-generated primitives — don't hand-edit
  site-footer.tsx  public footer: rides `.panel-inset` squared off, so the page
                   ends dark; disclosures are numbered notes, not buried prose.
                   Liquid Chrome (26 Nov 2026): it opens on the close line and
                   ends on `prism/chrome-wordmark.tsx` (the wordmark filled with
                   the hero's liquid metal through a text mask; the outline is
                   the fallback). `footer-market.tsx` holds the two async parts,
                   each in Suspense and each dropping out without data: the
                   close line (equal-weight average of the terrain's symbols
                   over 120 sessions, end dot at the latest close) and the
                   status strip (symbols tracked, US and India closes, nightly
                   refresh, `getServiceStatusCached()`, linked to /status);
                   their maths is in `lib/footer-market.ts`. The version is the
                   root package's. No source-code link until the project is
                   public (owner, legal review first)
  *.tsx            app-shell/sidebar/navigation, command-palette, earnings-calendar,
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
uv --directory apps/api run python -m stockviz.cli checklist
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
- **PRISM layer (Nov 2026 redesign)** sits on top of the Aurora rules below,
  which still hold (brand is identity/focus/selection only, gain and loss keep
  their own hues). The palette is **Liquid Chrome** (owner's pick, 25 Nov
  2026, after violet/pink/cyan, Volt and Solar passes): neutral ink black
  `#070708`, warm pearl text `#f2eee6`, and a polished-metal brand, champagne
  `#dcc49a` (`--brand`, also focus and selection), with a gradient from steel
  `#8d9bb0` through champagne `#f0dfba` to silver `#d6dbe2`. The metal has no
  hue of its own, so gain green (`#3ee59a`) and loss red (`#ff6b7f`) stay the
  only colours that mean something. `--input` is `#67645e` so field borders
  clear 3:1 (WCAG 1.4.11). The primary CTA (`.prism-cta`) is a polished-metal
  pill with ink text. The paper card is black titanium. The terrain's flat colour is
  `--text-tertiary`, never the brand, so up/down stays readable. Don't
  reintroduce navy or violet literals. Instrument
  Serif italic (`font-editorial`, `--font-editorial`) is for one or two words
  of a display headline only, usually with `text-prism` (animated light-band
  text); never for UI text, figures or tickers. The logo is
  `components/brand/stockviz-mark.tsx` (`StockVizWordmark` in every header and
  the footer): one chrome candle, a single stored close, in a black-titanium
  tile, with a glint that crosses it on hover. `app/icon.svg` is the same
  drawing as the favicon; change both together. `components/prism/`:
  - `liquid-chrome.tsx` + `liquid-chrome.glsl.ts`: hero/closing-CTA WebGL
    light (three.js, dynamic import): a pouring sheet of polished metal whose
    key light follows the pointer, drawn at 0.6x device pixels. Its mid-tones
    tint green/red with session breadth (`moodAmount`, at most 0.35); the
    hero chips state the figure. Keep GLSL in the `.glsl.ts` module. It
    replaced PRISM's `prism-field.tsx` ribbons, which had replaced
    `MarketWeather` (that canvas component is kept for its other users).
  - `market-terrain.tsx` + `terrain-data.ts` + `terrain-section.tsx`: the
    "time is the fourth axis" 3D surface from real stored closes (symbols
    with a full 120-session window ending on the same newest date). Landing
    variant `scroll` pins and scrubs time with scroll; dashboard variant
    `compact` autoplays while on screen. Both have a real range slider, text
    stats beside the canvas, a reduced-motion still frame and a 2D fallback.
    Never put DOM gradient overlays on top of its canvas; fade with
    `mask-image` on the host (an overlay made some compositors drop the
    WebGL layer).
  - `prism-cursor.tsx`, `magnetic.tsx`: public pages only, fine pointers,
    motion allowed. `tilt-card.tsx`: 3D tilt + glare around `PaperCard`.
    `spotlight-tracker.tsx`: one listener feeding `.spotlight` tiles their
    border light (border only, never behind a figure). `rolling-figure.tsx`:
    odometer roll on the headline portfolio value, plain text before and
    after the roll. `kinetic-marquee.tsx`: the oversized verb band.
  - three.js is allowed in `components/prism/` only, always dynamically
    imported inside an effect, rendering only while on screen. GSAP stays
    marketing-only.
  - `app/(product)/template.tsx` gives every workspace navigation the
    `.page-enter` rise; `[data-stagger]` children follow in sequence.
  - Use `mediaMatches()` (`lib/media.ts`), not `window.matchMedia`, in
    client effects: jsdom has no matchMedia.
- **Sound** (`lib/sound/engine.ts`, `components/sound/`): every sound is
  synthesised with Web Audio, no files. Off by default and remembered per
  browser (`localStorage["stockviz:sound"]`); the switch (`SoundToggle`, a
  real `role="switch"`) is in the workspace top bar and the public header.
  `SoundProvider` (in `providers.tsx`) gives buttons/links/tabs a tap, nav
  hover a tick and route changes a sweep. Forms call
  `useOutcomeSound(success, error, "fill" | "success")`; anything else can
  `emitSound(name)`. Mark a control `data-sound="none"` to silence it or
  `data-sound="<name>"` to pick its sound. A sound must never be the only
  signal: each one accompanies a visible change.
- **Dark only for now** (owner, 12 Nov 2026): `components/providers.tsx`
  sets `forcedTheme="dark"`, and the theme toggles are gone from the top bar,
  the public header, the footer and Settings. The light tokens stay in
  `globals.css` and `theme-toggle.tsx` stays in the tree, so the light theme
  can return after its own design pass. Don't design new screens light-first.
- **Title Case, never capitals** (owner, 26 Nov 2026): labels that used to
  be set in capitals (eyebrows, table and field labels, badges, chips, stamps)
  are written in Title Case. Don't use Tailwind `uppercase` or CSS
  `text-transform: uppercase`, and don't build display text with
  `toUpperCase()`. Pass dynamic labels through `titleCase()`
  (`lib/title-case.ts`; anything that isn't a string passes through). Labels
  use `tracking-[0.02em]`; the wide tracking that capitals needed is gone.
  Exceptions that keep their capitals, by convention: ticker symbols (and the
  ticker input boxes, which still upper-case what is typed), exchange codes
  (NSE, NASDAQ), currency codes (USD, INR), time zones (UTC), financial and
  indicator abbreviations (P&L, P/E, RSI, MACD, SMA, VWAP, VaR, XIRR, MAE,
  EOD), account initials in the avatar, and month names written by the date
  formatters ("Apr 7"). `titleCase()` leaves any all-capital or mixed-case
  word as written, keeps minor words (of, to, vs, and) lower inside a label,
  and leaves units such as 30d, bn and bps alone.
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
  and MACD (lines plus a sign-coloured histogram) in another; indicator
  values come warmed up from the API (Phase 6.1), so they do not change with
  the timeframe. The change pill is labelled "<tf> return since <first bar>"
  (UX-10).
- The stock page has a bar interval control (A1.4a: Daily / Weekly /
  Monthly, `?interval=1d|1wk|1mo`, default daily and left out of daily links)
  beside the lookback ranges, which stay ranges: `barsForLookback()` turns a
  range's trading days into weeks of five or months of 21 for the `limit`.
  The API resamples; the chart draws its candles and, when the newest bar is
  `partial`, a caption from `partialBarLabel()` ("Latest week so far
  (partial)...", also in the chart's text summary). Indicators follow the
  interval (the API leaves the partial bar out and the page says so); the
  metrics strip's RSI and 52-week range stay daily.
- Backtest results, saved runs (list and detail) show the run's `universe`
  stamp through `components/universe-note.tsx` (A1.4a): one neutral line,
  "Pinned symbol list, not point in time: survivorship-biased." plus the
  API's note. Not red: it describes every run today.
- Chart indicators come from the API registry (Phase 6.6): `STOCK_INDICATORS`
  in `lib/stock-workspace.ts` lists every study once (`key`, default-key
  `value`, label, `section`, group, parameter count), and `chartLayers()`
  splits the bundle by each indicator's `meta.pane`: price overlays
  (`.direction` outputs of Supertrend and Parabolic SAR are left out) and
  one pane per separate-pane indicator, all panes of the one chart (below).
  The first RSI and MACD keep their own panes whatever their parameters
  (`rsiKey`/`macdKey` on `PriceChart`; a non-default MACD's three outputs
  are zipped by `macdSeries`). A new study needs a menu entry; its
  parameters and badge come from the catalog.
- **Editable studies and evidence badges (A3.4, M2.6).** A chart key is the
  API's grammar (`rsi_21`, `bb_20_2.5`, `psar_0.02_0.2`; `macd` stays
  `macd` at its defaults). The stock page loads `getIndicatorCatalog()`
  (`/v1/indicators/catalog`, cached an hour, tag `bars`) first and
  `parseStockIndicators(raw, bounds)` keeps only known studies with
  parameters in bounds, written in full; without the catalog a key needs a
  known study and no more parameters than it takes, and a failed
  indicators call draws the chart without them. A decimal parameter has a
  dot, so split series keys with `splitSeriesKey()`, never on the first
  `.`. The toolbar's Indicators control is `IndicatorMenu`
  (`components/indicator-menu.tsx`, a Radix popover, so its inputs take
  typing and Escape closes it): each selected study is a `StudyEditor`
  form (number inputs with the catalog's min/max/step, a select for a
  `choices` parameter such as the pivot basis, an inline error for a value
  out of bounds, Enter or Apply pushes the new key, Reset puts the
  defaults back, Remove), then "Add a study" with a filter. Badges
  (`lib/indicator-badge.ts::indicatorBadge`): `Grade A-D`, "Too few",
  "Not graded" (job not run) or "No grade" (no canonical signal; never made
  up); the title says the signal and rule, the sample, horizon, figures, the
  universe stamp and "Association, not cause; not advice", and that a
  re-parametrised study shows its default's grade. `PriceChart` takes
  `badges` (by chart key) and shows each once in the legend
  (`legend-badge`, hidden on phones, where the menu carries them). The
  legend groups a study's outputs (`groupLegend`: "Ichimoku Cloud 9, 26, 52,
  26 tenkan … span A …") and on phones lists only the price pane's
  studies. Parabolic SAR's `.sar` draws as dots (`LineSpec.dots`). Ichimoku
  draws the cloud lines only on stored bars (no forward cloud). Tests:
  `tests/unit/indicator-params.test.tsx`.
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
- `/watchlist` lists (A2.5, M4.6; `lib/api/watchlist.ts` over
  `/v1/watchlists` and `/v1/column-sets`, actions in
  `app/(product)/(authed)/watchlist/actions.ts`): `?list=<id>` opens a list
  (default: the default list), `?tag=` filters its rows. `ListTabs`
  (`components/watchlist-lists.tsx`) is a row of links with each list's
  colour dot, a star on the default and its count; `ListManager` has New
  list, Edit (name, colour radios), Move left / Move right buttons (the
  keyboard path for reordering; no drag), Make default and a two-step
  delete that names the symbols going and what becomes the default.
  Colours are `--list-<name>` tokens in globals.css through
  `listColourVar()` (`lib/watchlist-columns.ts`): dots and a list's left
  edge only, never a gain or loss. Rows show the list's column set
  (`COLUMN_META` labels and `formatColumnValue`, an em dash for no data):
  `ColumnSetPicker` saves which set the list shows, `ColumnSetEditor`
  (in a `<details>`) ticks columns and orders them with Up/Down buttons,
  then saves over the set, as a new set, or deletes it. Each row's note and
  tags edit in place (`components/watchlist-row-editors.tsx`: Escape
  cancels, Ctrl/Cmd+Enter saves; tags as removable chips plus an input that
  takes "a, b"). Cards under `md` carry the same columns. News under the
  table is the open list's symbols. A failed lists call shows an error
  state; a failed rows call says the list could not be loaded. The add form
  and row remove post `watchlist_id`; without it `toggleWatchlistAction`
  uses the default list through the old `/v1/watchlist` routes.
- The stock page keeps the one-click star (default list, "Add AAPL to
  watchlist") and adds `AddToListMenu` (`components/add-to-list.tsx`,
  "Add to list…"): a disclosure with one checkbox per list from
  `listWatchlists(ticker)` (`contains`), ticking adds and unticking removes
  at once; Escape closes it. The screener's Compare form adds
  `BulkAddToWatchlist` for signed-in users: it reads the ticked `tickers`
  boxes (any number, up to 100) and adds them to a chosen list or a new one
  through `bulkAddAction`, reporting added / already listed / unknown with a
  link to the list; below `lg`, where cards have no checkboxes, it adds the
  page's results. The dashboard widget shows the default list (the old
  route), so "Make default" picks which list it shows.
- The stock page's Financials tab (`components/fundamentals-panel.tsx`,
  Phase 6.4) shows key multiples as of today with their reasons when null,
  the P/E percentile over five years of month-ends, and annual/quarterly
  statements labelled by period end and unit. It says when figures are not
  point-in-time (yfinance) and when the reporting currency differs from the
  trading currency. A failed financials call hides the panel, not the page.
- Charts use `lightweight-charts`, pinned at **5.3.0** (A3.1; exact pin,
  upgrade deliberately). The wrapper lives in `components/price-chart.tsx`;
  reuse it rather than instantiating a chart inline. Compare and backtest
  charts live in `compare-chart.tsx` and `equity-curve.tsx`. Canvas can't
  read CSS vars, so all three take their colours from `useChartPalette()`
  (`lib/chart-theme.ts`; `line`/`areaTop`/`areaBottom` come from
  `--foreground`), which reads the tokens off the document and re-reads on
  theme change — never hard-code chart colours. The hook keeps its object
  identity stable while colours are unchanged because callers pass it to
  `useEffect`, and a new identity forces a full chart rebuild. Fit the time
  axis with `fitWithLabelRoom()` (`lib/chart-range.ts`), not
  `timeScale().fitContent()`: it leaves room for the outermost date label,
  which lightweight-charts otherwise clips ("ug", "25"; UI audit P4). Bar
  times go through `barTimeToUtcSeconds()` (5.3 throws on unpadded
  business-day strings; we never pass strings).
- **One chart, many panes (A3.1, M2.1).** `PriceChart` is one `createChart`
  with native panes (series `paneIndex`, `chart.panes()`), so every pane
  shares one time scale, crosshair, zoom and pan; there are no other chart
  instances under it. `lib/chart-panes.ts::allPanes`/`assemblePanes` decide
  what goes where, in a fixed order: price (main series + overlays), volume
  (its own pane; `lastValueVisible`/`priceLineVisible` off), RSI (70/30
  guides), MACD, then each `chartLayers()` pane. Heights are stretch factors
  from `DEFAULT_PANE_HEIGHTS` (price 300, 240 on a phone; volume 80; RSI 110;
  MACD 130; others 100); the container's height is their sum plus the time
  axis. Separators drag (`layout.panes.enableResize`); on pointer-up each
  pane's height is saved per pane kind in localStorage
  (`stockviz:chart-panes`, `readPaneLayout`/`writePaneLayout`, try/catch, a
  convenience only) without a rebuild. Every pane but price has a header
  with a collapse arrow; a collapsed pane leaves the chart (rebuilt, the
  visible range kept) and shows as "Show <pane>" under it. The wrapper
  exposes `data-testid="price-chart"`, `data-pane-count` and `data-panes`.
- **Crosshair legend.** `lib/chart-legend.ts` (`buildLegendModel`,
  `legendAt`, `legendText`): top-left of the price pane, the hovered bar's
  date (`formatCloseDate`), O/H/L/C, change against the previous close,
  compact volume and every drawn indicator's value on that bar ("—" when it
  has none); with no bar hovered it reads the last bar (`data-last`).
  Values are matched by UTC seconds. It always reads the stored bar, also
  under Heikin-Ashi. Keyboard: the chart wrapper is focusable; arrows step
  the crosshair a bar (`setCrosshairPosition`, scrolling it into view),
  Home/End, `+`/`-` zoom around it, `0` fits, Escape clears; while it is
  keyboard-driven the legend sentence goes to an `aria-live="polite"` region
  at most every 600 ms. The keys are written in the "Chart keys and panes"
  disclosure under the chart (the wrapper's `aria-describedby`).
- **Chart types and scales (A3.1, M2.3).** `lib/chart-view.ts`: types
  candles, hollow candles, OHLC bars, line, area and "Heikin-Ashi (derived)"
  (`lib/heikin-ashi.ts`, pure, computed from the stored bars); scales linear,
  log, percent (`PriceScaleMode` on the price series' scale). URL state on
  the stock page: `?type=`, `?scale=`, `?adjustment=`, each left out at its
  default (candles, linear, adjusted) by `buildStockChartHref(..., view)`,
  so old links are unchanged. The toolbar adds a native "Chart type" select
  (pushes the URL), a "Price scale" segment and a "Price adjustment" segment.
- **Adjusted vs raw.** `symbol.has_raw` (API) says whether `eod_raw` holds
  rows; without it the Raw control is a focusable, inert `aria-disabled`
  button titled "Only adjusted prices are stored for this symbol", and a
  `?adjustment=raw` URL falls back to adjusted with a note. With it the page
  fetches `getBars(..., { adjustment: "raw" })` for the chart only (the
  header return and metrics stay adjusted), hides the price overlays (they
  are computed on adjusted prices and would jump at splits) and says so; a
  failed raw call falls back to adjusted, also said.
- **Drawings (A3.2, M2.4).** The stock page renders `ChartWorkbench`
  (`components/drawings/chart-workbench.tsx`): `DrawingToolbar` beside the
  chart (a row on phones, two columns from `sm`; every tool a named button
  with `aria-pressed`, then undo, redo, lock, delete), `PriceChart` with a
  `drawingLayer`, and `DrawingsList` under it. `PriceChart` attaches one
  series primitive to the price series (`lib/drawings/primitive.ts`), which
  draws every drawing; geometry, hit-testing and painting are pure in
  `lib/drawings/scene.ts` (labels kept inside the pane by `fitLabel`, crowded
  Fibonacci labels dropped), maths in `math.ts` (Fibonacci levels, ruler,
  position R), kinds in `kinds.ts`. **Anchors are bar dates and prices**
  (`lib/drawings/anchor.ts`): on weekly/monthly bars an anchor sits on the
  bar whose ISO week or calendar month contains its date (the API
  resampler's periods, so a holiday week's bar is its Thursday); a date with
  no bar is interpolated in time, outside the loaded bars extrapolated.
  Placing snaps to the bar under the pointer, clamped to the loaded bars.
  Pointer: with a tool, one click per anchor (Escape cancels); without one,
  a click selects (hit test), and the selected drawing's handles or body
  drag (`drag.ts`; mouse/touch starts are stopped in the capture phase so
  the chart does not pan). Keys inside the workbench: Delete/Backspace,
  Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z (or Y). Undo/redo is session-only
  (`history.ts`; undoing a delete re-creates with a new id, `remapId`).
  Saves go through `app/(product)/stocks/[ticker]/drawing-actions.ts` over
  `lib/api/drawings.ts` (server-only); signed out the tools are disabled
  with a "Sign in to save drawings" link; a failed load turns the tools off,
  not the chart. The list adds and edits any kind by typing dates and
  prices (the keyboard and phone path) and shows each position's R:R and
  risk per share. Raw prices hide the drawings (they are on adjusted
  prices). Colours are `useChartPalette().drawing` (`--list-<name>` tokens
  and the foreground). The wrapper exposes `data-drawing-count` and
  `data-drawing-tool`; list items `data-testid="drawing-item"` and
  `data-kind`. The test stub records attached primitives
  (`lwcCalls.primitives`) and maps price to `200 - y`, ten pixels a bar.
- **Anchored VWAP (A3.3, M2.5).** A drawing of kind `avwap`
  (`KIND_SPECS`: one date-only point, `dateOnly`, `needsLabel`): its
  `price` is `""` in the web's `DrawingPoint` and null on the API
  (`lib/api/drawings.ts::toApiPoints`); `style.bands` (0-2) picks the bands.
  The toolbar's "Anchored VWAP" tool places it with one click on a bar, with
  an "AVWAP label" field (default `avwap <date>`), a Bands select and quick
  anchors (highest high and lowest low of the loaded bars, the last earnings
  date through `lastEarningsDateAction`); the list adds and edits one by
  date, label and bands. `ChartWorkbench` fetches each one's line through
  `app/(product)/stocks/[ticker]/avwap-actions.ts` (`lib/api/avwap.ts`,
  `GET /v1/symbols/{t}/avwap`), keyed by `avwapKey` (id, anchor, interval,
  bands), so a new interval, anchor or band count fetches again; the API
  computes it from daily bars and samples weekly/monthly bars. The scene
  draws it with `avwapShapes`: one `path` shape per line (the VWAP, then
  dashed bands; one path so dashes run on), a tick at the anchor, the label
  and last value at the right end; a drag moves the anchor in time only.
- **Events, RS, delivery and the regime (A3.5, M2.7, M2.8, M3.1).**
  `lib/chart-events.ts` (pure): types from the API schema, `?events=` URL
  state (`parseEventsParam`, `resolveEventTypes`, `toggleEventsParam`;
  absent = news, earnings, dividends, splits, plus fills signed in; `""` =
  none; kept in `ChartView.events`, so every chart link carries it), and
  placement `eventBarIndex`/`eventsByBar`: weekly/monthly use the drawings'
  containing-period rule (`anchorBar`); daily the bar on the date, else the
  next bar (a Saturday headline shows on Monday); after the last bar, no
  marker (the list keeps it). The stock page fetches public events
  (`lib/api/chart-context.ts::getSymbolEvents`, cached an hour, tags
  `bars`/`news`) from the first bar to today and, signed in with fills
  shown, the viewer's fills server-side (`lib/api/events-server.ts`,
  authed, uncached; the API returns only the token's user's trades), then
  `mergeEvents`. `PriceChart` takes `events` and `currency`: one marker per
  type per bar on the price series (`createSeriesMarkers`; news shows the
  day's count, E/D/S letters, fills B/S arrows; colours from
  `palette.drawing` violet/amber/lime/blue/foreground, the toolbar dots use
  the same `--list-*` tokens); a click on a bar with events (not while
  placing a drawing) or Enter on the keyboard crosshair opens
  `EventPopover` (`role="dialog"`, Escape closes; news headlines with
  source and a link to the original, no text); the legend adds "Events:
  2 news, ex-dividend" (`legend-events`); `ChartEventsList` ("Chart events
  (N)" disclosure, newest first) is the keyboard path. The toolbar's
  `EventToggles` is a row of `role="switch"` links (`data-event-type`).
  The RS line (`rsline`, opt-in in the Indicators menu) is relabelled "RS
  line vs S&P 500 (^GSPC)" from `symbol.benchmark_name`; with no index
  closes its pane is not drawn (empty lines are dropped in `allPanes`) and
  `rs-empty` says so. `RelativeStrengthStrip` under the metrics strip
  (`relative-strength`): RS rank 1M/3M/6M/12M as ordinals with the return,
  "From 52-week high", and the universe stamp (`rs-universe`). Delivery:
  for `symbol.is_indian` the page loads `getDelivery()` and mounts a
  "Delivery %" pane (delivery and "20-day avg", `ChartPane.outputLabels`;
  points placed with `eventBarIndex`); without data a dashed
  `delivery-empty` line says "No delivery data yet", never an empty pane.
  Regime: `RegimeBadges` (async server component, `getRegime()` cached 10
  minutes) in `TopUtilityBar` beside the data-date chip, one
  `RegimePopover` per market (`regime-badge-<US|IN>`, `data-state`; the
  state word from `md`, a dot by state): state, index and as-of, the rules
  in order with met / not met / unknown, the inputs' values (breadth with
  "n of N"), the method and the disclaimer. Shell unit tests mock
  `@/components/regime-badge`. Tests: `tests/unit/chart-events.test.tsx`;
  the stub records markers (`lwcCalls.markers`) and click handlers
  (`clickAt`).
- **User-scoped rules (A3.3).** The rule panel says "Uses your drawings;
  only you can run it." (`data-testid="rule-user-scoped"`) when
  `/v1/rules/check` returns `user_scoped` (signed out: sign in to run it).
  `/screener` runs any rule as the signed-in user
  (`lib/api/screener-server.ts::getScreenerPageAsUser`, authed), so
  `drawing()`/`avwap()` resolve on their drawings; signed out the API
  refuses such a rule and the page says to sign in.
- **Replay chart (A4.6, M9.1).** `/replay/[id]` renders `ReplayChart`
  (`components/replay-chart.tsx`): `IndicatorMenu` (`?indicators=`, none by
  default; `replayIndicatorsHref` keeps the other params) above
  `ChartWorkbench` with `actions` (the session's own drawing actions,
  `replay/[sessionId]/drawing-actions.ts`) and `kinds`
  (`REPLAY_DRAWING_KINDS`: no anchored VWAP). `ChartWorkbench` takes
  `actions`/`kinds` (default: the live `/v1/drawings` actions, every kind);
  `DrawingToolbar` and `DrawingsList` take `kinds`. Indicators come from
  `getReplayIndicators` (`/v1/replay/sessions/{id}/indicators`, cut at the
  clock), events from `getReplayEvents` (news known by the clock and the
  session's fills), drawings from `listReplayDrawings`; the page never calls
  the live bars, indicators, events or drawings routes (the catalog is
  public metadata). Amounts format in `session.currency`. The ticket
  (`ReplayTradeTicket`) has an order type select (`replay-order-type`:
  market, limit, stop-loss, take-profit; stops sell-only), a price field
  (`replay-limit-price`) and says the order is checked from the next bar;
  an index session shows `replay-not-tradable`. `ReplayOrders`
  (`components/replay-orders.tsx`, `replay-order` with `data-status`,
  Cancel through `cancelReplayOrderAction`) lists resting orders; fills show
  fees (`replay-fill-fees`). The launcher lists every symbol with its
  currency, cash presets per currency (`replayCashPresets`), the lag note
  (`replay-lag-note`) and caps the end date at `max_end`. Tests:
  `tests/unit/replay-a46.test.tsx`.
- **Drills (A4.7, M9.3).** `/drills` (protected in `proxy.ts`, Research nav
  and subnav after Replay): decks (`drill-deck`) with the rule, universe,
  range, K of the eligible triggers (found, lag-skipped), N, M, seed and
  anonymisation; the process score line (`deck-score`, `deckScoreLine`);
  one `drill-row` per drill (`data-status`: not started, in progress,
  revealed; the label "Stock A" and no date while anonymised); a two-step
  delete (`DeleteDeckButton`, `deck-delete` then `deck-delete-confirm`).
  `/drills/new` is the launch form (`DrillLaunchForm`, a page rather than a
  modal: rule through `RuleFieldEditor` with setups, universe market /
  ticker list / watchlist, from, to, K (`drill-k`), N, M, seed, name, the
  anonymise box (`drill-anonymised`, on by default), Ctrl/Cmd+Enter
  creates; `createDeckAction` redirects to `/drills?deck=<id>`). Entry
  points link there through `drillLaunchHref` (`lib/drills.ts`): the
  screener rule panel (`rule-drill`, signed in, valid rule), each setup on
  `/setups` (`setup-drill`), a strategy backtest's "Rules as run"
  (`strategy-drill`: the entry rule, the run's tickers and range) and the
  event study (`study-drill`, signed in: trigger, universe, range).
  `/drills/[id]` uses only `/v1/drills` (`lib/api/drills.ts`): `DrillChart`
  (A4.6's `ReplayChart` with `basePath` and the drill's drawing actions),
  the shared `ReplayTradeTicket`, `ReplayMobileSheet`, `ReplayOrders` and
  `ReplayAdvanceControls` with `target="drill"` (a hidden `target` field;
  `replay/actions.ts` then calls the drill routes and revalidates
  `/drills`), `DrillPlanForm` (`drill-plan`, `plan-entry`/`plan-stop`/
  `plan-size`, planned risk; the ticket stays hidden until a plan exists;
  read-only once locked), `DrillRevealButton` (one step when finished, two
  to end early: `drill-end-early`, `drill-reveal`) and
  `DrillRevealPanel` (`drill-reveal-panel`: ticker, company, real and shown
  dates, `drill-after` returns, `drill-check` per check, `drill-r` with "not
  the score"). The page title is "Drill" and the URL holds ids only, so
  nothing names the symbol or a real date while anonymised; types come from
  the schema (`lib/drills.ts`). Tests: `tests/unit/drills.test.tsx`, guest
  e2e in `replay.spec.ts`.
- Other `PriceChart` users (`/trade`) get price and volume panes and the
  legend; they pass no indicators. Unit tests mock the library with
  `tests/stubs/lightweight-charts.ts` (records series, panes, price lines,
  crosshair calls): `vi.mock("lightweight-charts", async () => (await
  import("../stubs/lightweight-charts")).lwc)`.
- Server components by default — only mark `"use client"` when you need state,
  effects, or interactivity.
- Research (`/compare`, `/backtest`, `/checklist`, `/replay`) is one
  domain. See [`docs/RESEARCH.md`](../../docs/RESEARCH.md). Keep URL state
  shareable (`tickers`/`tf`, `ticker`, `min`/`dimension`/`sort`/`q`). Replay Lab is
  future-blind historical simulation; never fetch live bars or
  news into `/replay/[id]` (A4.6: its indicators, events and drawings come
  from the session's own routes, cut at the clock). Forensics (`?view=forensics`) may call session
  `/forensics`, `/journal`, `/history`, `/summary`, and `/fills` only.
- `/backtest` starts on the first symbol with stored closes and ends its
  range at that symbol's latest close (`lib/backtest-defaults.ts`, UI audit
  F1), using `last_close_at` from the markets summary. The range follows the
  chosen symbol until the dates are edited by hand. Since A4.3 a template run
  goes through `app/(product)/backtest/holdout-actions.ts::runTemplateAction`
  (authed when signed in, so it lands in the user's trial ledger; signed out
  public with `checkVisitorLimit("strategy")`), not the browser.
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
- **Costs (A4.2, M7.2).** `lib/fees.ts` (types from the schema,
  `FEE_SCHEDULE_OPTIONS` with `auto` first, `BROKERAGE_OPTIONS`,
  `advCapValue`, `partialLabel`, `versionRange`, `sourceDated`,
  `feesSuffix`) and `lib/api/fees.ts` (`getFeeEstimate`, a browser call to
  the public `/v1/fees/estimate`; `getFeeSchedules`). Both `/backtest` modes
  send `fee_schedule` (default `auto`), `brokerage` and `adv_cap_pct`
  (default 10; empty is off) and show `CostsDisclosure`
  (`components/costs-disclosure.tsx`, `data-testid="costs-disclosure"`:
  each dated version's components with rate, side and a link to the source,
  fills before the confirmed date, the price-band and ADV notes, a link to
  `/docs/costs`). Results are net first ("Net return", then "Gross
  return"); a capped entry says "partial: N of M shares"
  (`partial-fill`). The order review (`OrderReview`) fetches the estimate:
  the headline and "Estimated total, after fees" are net, "Value before
  fees" second, and a "Costs" `<details>` (`order-costs`) lists each fee
  with its source. Fill confirmations append fees and the net amount;
  `/trades` shows the net total (value and fees under it) and net realized
  P&L with gross under it; `PortfolioMetrics` shows "Realized P&L, net"
  with fees and gross in the detail. `/backtest/runs` labels "Net return"
  with gross under it when stored. `/docs/costs` (its own dynamic route,
  `app/(public)/docs/costs/page.tsx`, outside `[slug]`'s static params)
  renders `components/docs/costs-schedules.tsx` from the API: Indian
  schedules first, the version in force today open.
- `/backtest?mode=rule` (A4.1, M7.1): the Rule strategy mode beside the
  templates (`ModeTabs` links, `data-testid="backtest-mode"`). The page
  loads the public presets and, signed in, `listSetups()` and
  `listWatchlists()`; `RuleStrategyForm`
  (`components/rule-strategy/rule-strategy-form.tsx`): entry and exit
  `RuleFieldEditor` (`rule-field.tsx`: `checkRule()` debounced as on the
  screener, `rule-ok` / `rule-error`; "Load a setup…" sends that version by
  id until the text is edited), universe radios (one symbol, watchlist
  (signed in), ticker list), dates, stops, sizing, costs, direction and
  shortable list. Run is disabled while a rule is invalid or `formProblem()`
  says why; Ctrl/Cmd+Enter runs from any field. Pure helpers in
  `lib/rule-strategy.ts` (`buildStrategyRequest`, `tradeMarkers`,
  `REASON_LABEL`/`REASON_CODE`, `formatR`). Runs go through
  `app/(product)/backtest/strategy-actions.ts::runStrategyAction` (authed
  when signed in, else public with `checkVisitorLimit("strategy")`, 20 a
  minute), not the browser. `RuleStrategyResults` (`rule-strategy-results.tsx`):
  "Performance, net of costs" (net return first), then gross, costs,
  Sharpe, drawdown, trades and mean R; the unknown / ignored / skipped
  counts (`strategy-counts`); the notes and stop priority in a "How this
  run was simulated" disclosure; Save run (`SaveStrategyRun`, kind
  `strategy` through `saveBacktestRunAction`); `StrategyTradesChart`
  (`PriceChart` with `markers`: B/S entries, exits coded X/SL/ATR/TS/T and
  "gap", colours from `useChartPalette()`; a basket picks a symbol; bars
  through `strategyBarsAction`); the equity curve; the trades table
  (`strategy-trades`, reason and `gap-flag`, R; on phones reason and R sit
  under the P&L; 50 rows, then "Show all"). `/backtest/runs/[runId]` shows
  a `strategy` run with the same component (no Save). Tests:
  `tests/unit/rule-strategy.test.tsx`, the e2e in `research-workspace.spec.ts`.
- `/backtest?mode=rotation` (A4.4): `RotationForm`
  (`components/rotation/rotation-form.tsx`): the ranking is a
  `RuleFieldEditor` checked with `checkNumber()` (`/v1/rules/check` with
  `expect: "number"`), top N, schedule, buffer, weighting, an optional cash
  filter rule (setups loadable), universe (ticker list with "All US (n)" /
  "All India (n)" quick fills from `marketTickers()`, or a watchlist signed
  in), dates (ten years to the latest close by default), costs and holdout.
  Helpers in `lib/rotation.ts` (`buildRotationRequest`, `rotationProblem`,
  `rebalanceSummary`, `symbolMarket`). Runs through
  `app/(product)/backtest/rotation-actions.ts::runRotationAction` (authed or
  public with `checkVisitorLimit("strategy")`). `RotationResults`
  (`rotation-results.tsx`, `rotation-results`): net first, then gross,
  costs, Sharpe, drawdown, turnover a year and a rebalance; report card,
  overfitting checks (unlock sends `{rotation}`), Save run
  (`SaveStrategyRun kind="rotation"`); "Holdings by rebalance"
  (`rotation-rebalances`, newest first, 24 then all: held after, in, out in
  neutral colours, turnover, a "Ranking" disclosure with the values and the
  unranked; on phones in/out and turnover sit under the holdings); the
  equity curve; round trips linked to stock pages. Saved `rotation` runs
  render the same component. Tests: `tests/unit/rotation.test.tsx`, e2e in
  `research-workspace.spec.ts`.
- `/event-study` (A4.5, Workbench nav and subnav, public): a GET form
  (`components/event-study/event-study-form.tsx`): trigger
  `RuleFieldEditor` with setups, news and delivery preset buttons
  (`TRIGGER_PRESETS`), universe (market, ticker list, watchlist signed in),
  from, to, cooldown. URL state parsed by `lib/event-study.ts`
  (`parseStudyParams`, `studyRequest`, `eventStudyHref`); the page runs the
  study on the server (`runScanEventStudyAsUser` in
  `lib/api/research-server.ts` signed in, else `runScanEventStudy` with
  `checkVisitorLimit("eventStudy")`, 10 a minute). `ScanStudyView`
  (`scan-study-view.tsx`, server-renderable): trigger and sample line, the
  disclaimer (`scan-disclaimer`), one `scan-horizon` card per horizon (n,
  incomplete, overlapping; mean and median net and excess, base rate, hit
  rates, t and clustered t, percentiles, an inline SVG histogram) or
  "Too few events" (`scan-too-few`) under the minimum; the method, the
  universe stamp; events (`scan-events`, 25 then a disclosure) linked to
  `/stocks/[t]`. "Run event study" links: the screener's rule panel
  (`rule-event-study`, valid rules) and each setup on `/setups`
  (`setup-event-study`). `/news-reactions` is unchanged. Tests:
  `tests/unit/event-study.test.tsx`, e2e in `research-workspace.spec.ts`.
- **Report card and overfitting checks (A4.3, M7.4).** `lib/report-card.ts`
  (types from the schema, `HOLDOUT_OPTIONS`, `formatMetric`,
  `probabilityWords`, `heatShare`, `templateRoundTrips`).
  `components/report-card/report-card.tsx`: `ReportCard` (`report-card`:
  every metric on a `FigureStrip`, net, each with `FormulaTip`, an "i" button
  (`formula-tip`, Enter/click toggles, Escape closes) that shows the formula
  inline; a null value shows its reason), `McFan` (`mc-fan`: drawdown
  percentiles, inline SVG band 5-95 and median, the seed) and `RegimeTable`
  (`regime-split`, sessions, return, Sharpe, exposure, entries; on phones
  Sharpe sits under the return). `overfitting-checks.tsx`:
  `OverfittingChecks` (`overfitting-checks`: N (`trials-n`), PSR, DSR
  (`dsr-value`) with the API's meaning sentence, the best-of-N bar, the
  variant definition) and the holdout panel (`holdout-panel`,
  `data-status`): locked shows "Unlock holdout…" then a warning and "Unlock
  once, now" (`holdout-unlock`, `holdout-confirm`; a two-step confirm through
  `unlockHoldoutAction`); seen shows the unlock time and the holdout's
  result. `sweep-checks.tsx`: `PboPanel` (`pbo-panel`, logit histogram) and
  `PlateauHeatmap` (`plateau`, Net Sharpe / Net return radios, the best cell
  outlined, `plateau-isolated` warning). Both `/backtest` forms have a
  Holdout select (last 20% locked, default; or none) and show the run's
  window note (`run-window`); the template result also draws its trades on
  the price chart (`StrategyTradesChart` with `templateRoundTrips`). Saved
  runs: `single` shows the report card and live `checks`, `strategy` passes
  `checks` to `RuleStrategyResults`, `sweep` shows PBO and the heatmap.
  Tests: `tests/unit/report-card.test.tsx`.
- The `/trade` option ticket (`components/option-trade-form.tsx`) quotes
  before it buys (audit LG-7): `getOptionQuote()` (`lib/api/option-quote.ts`,
  a browser call to the public `/v1/options/quote`) shows spot with its close
  date, volatility, value per share and premium, and the buy button names the
  premium. The strike starts at the money and follows the symbol until edited.
  Only USD symbols are offered. Phase 9.1 adds the risk-free rate, the
  number of closes behind the volatility, a note when the premium is the
  1-cent floor (LG-14), `GreeksList` (per share, with what each means for one
  contract) and a collapsed "Saw a different premium?" check that calls
  `getImpliedVolatility()` (read only; the buy is still charged at the
  quote). The portfolio options table shows each contract's delta and theta
  from `PortfolioOption.greeks`, a dash when it cannot be priced. Phase 9.2:
  the ticket's "Buy to open" / "Write covered" choice posts `side`; writing
  explains the cover (100 shares per contract, or the strike value in cash),
  quotes with `side=short` and shows what is held back, the most it can lose
  and gain and the breakeven (`riskRows`), with the position's (negated)
  Greeks. Written legs show as "Covered call (written)" / "Cash-secured put
  (written)" with the premium received, and `CloseOptionButton short` reads
  "Buy back". Phase 9.5: `/trade` shows the single-contract ticket beside
  `StrategyBuilder` (`components/strategy-builder.tsx`): a template from
  `STRATEGY_TEMPLATES` (`lib/api/option-strategies.ts`), strikes defaulted
  around today's close by `defaultStrikes` (step 1/5/10 by price) and
  editable, expiry (near and far for a calendar), contracts. It calls the
  public `getStrategyPayoff()` (a browser `apiPost`) and shows the legs,
  net premium, cash held back, most it can lose and gain, breakevens, the
  model chance of profit and `PayoffChart` (`components/payoff-chart.tsx`,
  inline SVG: solid at the first expiry, dashed today). Placing is
  two-step: "Review strategy" then "Place …", posting `review_step=confirmed`
  and a client key to `openStrategyAction`, which refuses a draft.
  `/portfolio?tab=options` loads `getOptionsBook()` and `listStrategies()`
  only on that tab (`loadPortfolioData(..., { options })`; the book also on
  Analytics) and shows `OptionsGreeks` and `ExpirationView`
  (`components/options-book.tsx`), `PortfolioStrategies` with a two-step
  "Close strategy", then the legs. The Analytics tab shows `OptionsGreeks`. Phase 9.6: the ticket states its
  `volatility_method` (a stored chain's IV or 30-day historical), and the
  builder has a collapsed "Volatility smile" (`components/volatility-smile.tsx`,
  `getOptionSurface()`, inline SVG; each strike from its out-of-the-money
  contract) that says when no chain is stored. `PortfolioMetrics` adds an "Other cash" figure
  when `cash_by_currency` (Phase 4.5b) holds a non-base currency: a sale of a
  EUR stock keeps its euros. The portfolio header and the dashboard hero
  show `ValuationNotice` when `valuation_warnings` is not empty (audit LG-13).
- **Books (A5.1, A5.2).** `lib/api/books.ts` (server-only): `listBooks`,
  `createBook`, `updateBook`, `deleteBook`, `withBook(path, book)` (appends
  `book=<id|all>`). Every fetcher in `lib/api/trading.ts`, `options.ts` and
  `journal.ts` takes an optional book. **URL rule** (`lib/book-url.ts`,
  client-safe): the book is `?book=<id>` or `?book=all` on `BOOK_PAGES`
  (dashboard, portfolio, trade, orders, trades, settings); absent = the
  default book. `all` is allowed on all but settings (`ALL_BOOKS_PAGES`).
  `lib/book-context.ts::loadBookContext(raw, path, query)` (server) loads the
  list and returns `{books, book, selected, isAll, tradeBlock, limit}`; an
  unknown id falls back to the default; with no `?book=` a valid `sv_book`
  cookie (written by the switcher, a convenience only) redirects to that book.
  Links: `components/book-link.tsx::BookLink` carries the page's `?book=` to
  other book pages (portfolio, dashboard and operational components and
  `PageSubnav` use it); `buildPortfolioHref({book})`; the order ticket keeps
  it when the symbol changes. **Switcher**: `components/book-switcher.tsx`
  (client: disclosure + links, arrows/Escape, phone-width panel under the
  bar), loaded by `book-switcher-slot.tsx` in `TopUtilityBar` (signed in):
  name, kind badge, currency, holder, archived, All books (2+ books) and
  Manage books (`/settings#books`). **Tickets**: `ticket-book-line.tsx`
  ("Trades into X (CUR)"), hidden `book_id` read by the server actions
  (`bookIdFromForm`); `tradeBlockReason` disables the order ticket, option
  form and strategy builder in All books, archived and imported books. The
  stock page's ticket trades into the default book and says so.
  **Settings → Books** (`components/books-panel.tsx`,
  `settings/book-actions.ts`): create (name, USD/INR, paper/imported, holder
  kind and label, no PAN field), rename, make default, archive/unarchive,
  delete (two steps: what goes, then the name typed back; only empty or
  archived, never the default); the cap shown. Account currency and risk
  limits on Settings are the selected book's. **All books** views:
  `CombinedBooksPanel` (each book's share, the FX rule, what is per book),
  `PerBookOnly` stands in for journal, income, options Greeks, attribution,
  risk, stress and rebalancing; trades and orders add a Book column/chip;
  realized P&L is not totalled across currencies. `calculateNavChange` leaves
  out All books `flow` (new books, imported buys) and chains the returns.
  `scripts/seed-demo.mjs` writes snapshots into each demo user's default book.
- **Broker status (A5.7, M1.7).** No live broker connection. `lib/api/brokers.ts`
  (server-only, `getBrokerStatusOrNull()` never throws) reads
  `/v1/broker/status`; `lib/broker-status.ts` (pure) turns each state into
  words (`brokerCopy`: headline "Zerodha: not connected." / "snapshots
  only." / "offline.", the detail, e.g. "Live broker data needs a paid Kite
  Connect app; not set up.", and `IMPORT_LINE` "Imported books update when
  you upload a tradebook (CSV)."; `brokerLine` for one line).
  `components/brokers/broker-status.tsx`: `BrokerStatusList`
  (`broker-status`, one item per broker with `data-state` and a badge; null
  = "could not be read just now") on Settings (a Brokers panel) and
  `/status` (a Brokers section, signed in only; signed out it says to sign
  in), and `BrokerStatusLine` (`broker-status-line`) in an imported book's
  empty state (the portfolio page fetches the status only for an imported
  book; `BookStateNotice` adds the line once the book has imports). The
  switcher adds `IMPORTED_BOOK_NOTE` (`switcher-broker-note`) under imported
  books, static text, so the top bar makes no extra call. Never an error
  page. Tests: `tests/unit/a57-broker-status.test.tsx`.
- **Tradebook import (A5.3, M10.2).** `/portfolio/import?book=<id>`
  (`app/(product)/(authed)/portfolio/import/`; a book page, so the switcher
  keeps it; "Import tradebook" in the Portfolio & Tax sidebar group and the
  palette). A paper book, All books, an archived or a non-INR book get an
  empty state saying where imports go. `components/tradebook-import.tsx`
  (client): the format-unconfirmed note ("tell us the header row"), file
  input -> **Preview** (counts, a "Columns Matched" disclosure with the
  header each field came from and ignored headers, the first new trades
  with estimated charges and split restatement, problems by row) ->
  **Confirm Import**; the file stays in component state between the two
  calls and commit sends it again with the preview's `file_sha256`. Below:
  sells waiting for an opening lot, the opening-lot form and list, and
  Import History (counts per batch, a two-step delete whose outcome is
  announced by the list, not the deleted row). Server actions in
  `portfolio/import/actions.ts` check the file (`lib/tradebook-import.ts`:
  `checkTradebookFile`, 2 MiB, CSV not XLSX; labels `PROBLEM_LABELS`,
  `countItems`) and post its bytes through `authedPostText` (`lib/api/
  server.ts`, a raw body with its own content type) via `lib/api/imports.ts`.
  **Next 16 caps server-action bodies at 1 MB by default**
  (`node_modules/next/dist/docs/.../serverActions.md`): `next.config.ts`
  sets `experimental.serverActions.bodySizeLimit: "2200kb"` (2 MiB plus
  multipart overhead; the API still refuses past 2 MiB). `BookStateNotice`
  links "Import Tradebook (CSV)" on an imported book that is not archived;
  Settings → Books creates imported books in INR. Nothing logs the file.
  Tests: `lib/tradebook-import.test.ts`.
- **Trade plans (A5.4, M10.3).** Types and the ticket helpers are
  client-safe in `lib/plans.ts` (`planFigures` risk/reward/R:R and the first
  problem, `planFormFields` / `planFromForm` (the `plan_*` hidden fields a
  ticket posts), `splitTags`, `planBadge`); `lib/api/plans.ts` (server-only)
  has `listPlans(book)`, `createPlan`, `updatePlan`, `deletePlan` and
  `planPickerOptions()` (your setups' newest versions and presets, your open
  theses; `/trade` and the stock page load it, a failure leaves the pickers
  empty). Both paper tickets show `TicketPlanSection`
  (`components/ticket-plan.tsx`, `ticket-plan`, figures in
  `ticket-plan-figures`) for a buy (market or limit): a "Plan this trade"
  checkbox that starts from the order's price and quantity, entry, stop,
  target, size, setup, a thesis of this ticker, "Thesis (your words)", why
  now and tags. `OrderReview` takes a `plan` slot: `PlanReview`
  (`review-plan`: entry, stop, target, size, risk if stopped, reward : risk,
  setup, the lock sentence) renders the hidden fields, and
  `placeTradeAction` / `placeOrderAction` send them as the API's `plan`
  (buys only; an invalid plan returns "Plan: ..."). The fill confirmation
  adds "Your plan locked at this fill". The Portfolio **Journal** tab shows
  `TradePlansPanel` (`components/plans/trade-plans-panel.tsx`,
  `trade-plans`) above the P&L calendar for the selected book
  (`loadPortfolioData(..., { plansBook })`; not in All books): a status
  filter, one `plan-row` per plan (`data-status`, `data-badge`;
  `plan-badge` Locked / Written after entry / Not filled yet / Closed /
  Cancelled), opening to its details and an editor (notes and tags always;
  prices and why only while open and unfilled; Cancel plan, Close plan)
  through `portfolio/plan-actions.ts`; "Plan an open position"
  (`plan-open-position`) for holdings without an active plan creates one
  with `link_open_position`, labelled written after entry. The replay
  journal says when it was written after entry. Tests:
  `tests/unit/trade-plans.test.tsx`; the signed-in trade e2e plans a buy in
  the second book (Locked) and an open position in the default one
  (Written after entry).
- **Journal entries (A5.5, M10.3).** Types and labels are client-safe in
  `lib/journal-entries.ts` (`entryPlanBadge` Locked plan / Written after
  entry / No plan, `BADGE_CLASS`, `rText`, `excursionPct`, `money`,
  `entryHref`, `splitEntryTags`); `lib/api/journal-entries.ts` (server-only)
  has `listJournalEntries(book | "all")`, `getJournalEntry`,
  `patchJournalEntry`. Every figure comes from the API (computed on read);
  the web never recomputes P&L, R, MAE or MFE. The Portfolio **Journal** tab
  shows `JournalEntriesPanel` (`components/journal/journal-entries-panel.tsx`,
  `journal-entries`) above the plans and the P&L calendar
  (`loadPortfolioData(..., { entriesBook })`; in All books it lists every
  book and replay session, and plans and the calendar stay per book): status
  and source chips, one `journal-entry-row` per round trip (`data-status`,
  `data-source`: symbol, source and plan badges, dates, `entry-r`,
  `entry-pnl`, `entry-mae`, `entry-mfe`, size), each a link to
  `/portfolio/journal/[id]` (`?book=` kept; mapped to the Portfolio item
  through `matches: ["/portfolio", "/portfolio/journal"]`). The entry page
  (`app/(product)/(authed)/portfolio/journal/[id]/page.tsx`, 404 for
  another user's) has a `FigureStrip` (net P&L with estimated charges, R
  with its risk or reason, MAE and MFE with money and date, average entry,
  exit or the mark, holding), the basis note (`entry-basis`: "Daily bars: may
  include moves before entry or after exit" for paper and imported),
  `JournalEntryChart` (`journal-entry-chart`: `PriceChart` with the fills as
  fill events, the closing one carrying R, MAE/MFE circles as `markers`, and
  the plan's entry, stop and target as `priceLines`; bars from 21 days
  before entry to 10 after the exit, a replay entry never past its last
  fill or mark), the plan with the drill's adherence checks
  (`entry-adherence`) or the written-after-entry note, the fills, News at
  Entry / Exit (`news-at-entry`, `news-at-exit`; headline, source, date and
  link; "No news copy for this date" before the sync's first document) and
  `JournalReviewForm` (`journal-review-form`: review notes, mistakes,
  lessons, setup and mistake tags; Ctrl/Cmd+Enter saves; through
  `portfolio/journal-actions.ts`). `PriceChart` takes `priceLines`
  (`PriceChartLine`). **R on fill markers:** a fill event with `r_multiple`
  (the closing fill of a journal entry, from the API) is marked "S +0.97R"
  and its summary says "closing the trade at +0.97R" (`formatR` in
  `lib/chart-events.ts`); opening and partial fills stay "B"/"S". The P&L
  calendar's caption says fills are dated on each exchange's own day.
  Tests: `tests/unit/journal-entries.test.tsx`.
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
  after success. The Replay ticket is separate and still single-step (A4.6:
  with limit and stop orders that rest across steps).
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
- `/screener` Rule panel (A2.2, `components/rule-panel.tsx`): a Rule DSL
  condition refines the filters. The panel is a GET form to `/screener`, so
  the rule is URL state (`?rule=`, `?rule_mode=met_only|all`; default met
  only) and a screen with a rule is a link; it carries the filters and sort
  as hidden fields (`carriedFields`), and the filter form carries the rule
  back. The rule also shows as a removable chip and stays in a saved
  screen's query. As the user types, `checkRule()` (`lib/api/rules.ts`, a
  browser `apiPost` to the public `/v1/rules/check`, 400 ms debounce, the
  previous request aborted) shows an error with its line and a caret under
  its column, or the canonical form, warm-up and what it reads; Run is
  disabled while the rule is invalid; Ctrl/Cmd+Enter runs it. Presets come
  from the public `listPresets()` (`lib/api/setups.ts`, cached an hour):
  pick one to read its source and limits, Load it into the editor, or Fork
  it (signed in). "Save as setup" (signed in, enabled only for a valid
  rule) and Fork are server actions in `app/(product)/screener/actions.ts`
  over `lib/api/setups-server.ts`. With a rule the table adds a Rule column
  (met / not met / unknown with the reason) and cards a Rule figure; the
  count line says how many filtered symbols the rule judged, the counts and
  the session per venue, with a link to the other mode; a 422 shows the
  rule's error. Every page ends with `UniverseNote` (the screen's
  survivorship stamp).
- `/setups` (A2.2, protected, Research nav after Screener): your setups and
  the presets, each with its rule, "Open in screener"
  (`screenerHrefForRule`, `lib/setups-view.ts`), Fork, Archive (yours), and
  `?open=<id>` to list one setup's versions (one extra call); `?archived=1`
  shows archived ones. Actions in `app/(product)/(authed)/setups/actions.ts`.
  There is no editor for a setup's next version yet: open it in the
  screener and save it again (a new setup); `POST /v1/setups/{id}/versions`
  exists for A2.3.
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
- **The six-workspace shell (A3.6, 26 Nov 2026).** `lib/app-navigation.ts`
  is the one route → workspace map (`WORKSPACES`); the sidebar, the command
  palette, the workspace subnavs and the page eyebrows all read it. No URL
  moved, so old links still work.

  | Workspace | Routes (sidebar items in order) |
  | --- | --- |
  | Today | `/dashboard` (Home; `/` for guests), `/notifications` |
  | Markets | `/markets` (Overview), `/screener`, `/earnings`, `/news` |
  | Workbench | `/setups`, `/checklist` (+ `/recommendations`, a redirect), `/compare`, `/event-study`; `/stocks/*` belongs here without an item (`extraMatches`) |
  | Quant Lab | `/backtest`, `/backtest/runs` (Saved runs, + `/runs/[id]`), `/replay` (+ `/[id]`), `/drills` (+ `/new`, `/[id]`), `/news-reactions` |
  | Portfolio & Tax | `/portfolio` (journal and A5.4 plans are its Journal tab), `/trade`, `/orders`, `/trades`, `/watchlist`, `/alerts`, Books (a signed-in shortcut to `/settings#books`, never "current") |
  | AI Copilot | `/copilot`: a placeholder page until A8 (no input, no sample answers; it lists what is planned) |
  | Bottom rail (`UTILITY_NAVIGATION`) | `/status` (everyone), `/settings` (signed in) |

  The sidebar (`components/app-navigation.tsx`) draws each workspace as a
  labelled group (`role="group"`, `data-workspace`, `data-active`): the
  heading is not a link and lights up for any of its routes; the item with the
  longest matching prefix gets `aria-current="page"` (so `/backtest/runs`
  marks Saved runs, not Backtest). `item.note` renders a small chip (the
  Copilot's "A8"). Icons are in `components/navigation-icons.ts`
  (`NAV_ICONS` by href, `WORKSPACE_ICONS` by id), shared with the palette.
  `ResearchSubnav` lists the current workspace's items ("<Workspace> tools")
  and `ResearchPageHeader path="/x"` takes its eyebrow from the workspace.
  **To add a route:** add the page, then an item in its workspace (or a prefix
  in `extraMatches`), and an icon in `NAV_ICONS`.
  `tests/unit/app-navigation.test.ts` walks `app/(product)/**/page.tsx` and
  fails while a page is unmapped; the palette picks the item up by itself.
  The wordmark carries the `EOD · Simulated` tag, and the top bar shows
  `DataDateChip` (`components/marketing/market-status.tsx`), the newest stored
  bar's date. It is an async server component, so unit tests that render the
  shell mock that module.
- **Command palette (A3.6)**: `components/command-palette.tsx` (replaced
  `global-ticker-search.tsx`), data in `lib/command-palette.ts`. ⌘K / Ctrl+K
  anywhere in the product app (again to close), `/` outside a field, or the
  top-bar button ("Search tickers, pages and actions": a field from `sm`, an
  icon on phones). Sources: pages (every sidebar item and the bottom rail),
  actions (`ACTIONS`: New backtest, Start a blind replay, Create drill deck,
  New screen, Compare symbols, Place a paper order, Create price alert, Open
  journal and plans, Switch book…, Manage books; account-only ones hidden from
  guests), symbols (`searchSymbols`, debounced, newest request wins), recent
  picks (localStorage `stockviz:palette-recent`, 5, every access guarded).
  With no query: Recent, Suggested (the current workspace's other pages, then
  a few actions), Popular Symbols. Ranking (`scoreCommand`): every query word
  must start a word of the label, workspace or keywords; whole label words
  and a label prefix rank first. Keyboard and a11y: Radix Dialog ("Command
  palette", focus trap, page inert); focus stays in the `role="combobox"`
  input with `aria-activedescendant` into a `role="listbox"` of labelled
  `role="group"`s; the first option is active; ↑/↓ wrap, Enter opens, Escape
  closes and focus returns to the trigger; a polite live region counts
  results. Book pages keep `?book=` (`resolveCommandHref`); a symbol keeps the
  stock page's `tf` and `indicators`. "Switch book…" dispatches
  `OPEN_BOOK_SWITCHER_EVENT`, which `book-switcher.tsx` listens for (it opens
  with focus on the first book). The panel sits near the top (`top-3`, `sm:
  top-[12vh]`) so results grow downward and the phone keyboard never covers
  the input.
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
  (GDELT sends none, audit AG-12).
  News for a set of symbols is one call, `getNewsForTickers()` (`/v1/news?tickers=`):
  `/watchlist` lists it under the table, and `/portfolio?tab=news` loads it
  for the holdings only while that tab is open, as Journal does. `/news` has
  two views (`?view=`): listed companies (default, linked documents) and
  `market` (`getMarketNews()`, `/v1/news?scope=market`: documents linked to no
  symbol), so a general headline is never shown as news about a symbol. The
  dashboard's `NewsWidget` (`components/dashboard/news-widget.tsx`) shows the
  five newest headlines on the holdings and watchlist (`dashboardNewsTickers`
  in `lib/dashboard-news.ts`), loaded after the rest as the page's one second
  call and degrading to its own empty state.
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
  mark read / mark all read.
- A2.3: `AlertForm` adds "Rule (saved setup)" (`kind: "rule"`): a picker
  of the setups' newest versions in two groups (yours, presets) from the
  `setups` prop (`AlertSetup`; `/alerts` loads `listSetups()`, the stock
  page's popover passes none and links to `/setups`), the chosen rule's
  canonical text, and a preview saying missing data counts as not met. The
  action posts `setup_version_id`. Saved screens (`components/saved-screens.tsx`)
  with a rule show `NotifyToggle` ("Notify me when members change",
  `toggleScreenNotifyAction`): a screen whose rule is only URL text first
  gets a setup (your own with the same rule hash, else a new one named after
  the screen) and is re-saved with its version; re-saving a screen with the
  same rule keeps its version and flag. `/notifications` has a Screens tab
  and shows a screen item's entries and exits as ticker links
  (`components/screen-changes.tsx`, from the notification's `data`).
  Settings has a Notifications panel (`components/notification-channels-panel.tsx`,
  actions in `app/(product)/(authed)/settings/notification-actions.ts`,
  `lib/api/notifications.ts`): webhook URL and secret (write-only: blank
  keeps it, the field says "set"), email address (blank = the account
  email), Telegram chat id with a one-line how-to, a "Send" checkbox per
  category (unticked = muted on that channel), an enable box, Save and Send
  test; a channel whose server config is missing reads "Not available on
  this server.", not an error. Browser push is not built.
- `/checklist` (A2.4, M4.4, Workbench nav and subnav, public): the
  Checklist that replaced the 7-vote Signals. `getChecklist()` /
  `getSymbolChecklist()` (`lib/api/checklist.ts`, public) read
  `/v1/checklist` and `/v1/symbols/{t}/checklist`; helpers in
  `lib/checklist-view.ts`. The page (server component) shows "The six
  dimensions" (`DimensionGuide`: summary, each setup's canonical formula per
  scope (Volume / delivery has an NSE/BSE setup and an outside-India one),
  the grade badge, its sample and survivorship note, the source), then one
  native `<details>` card per symbol (`ChecklistSymbol` in
  `components/checklist/checklist-view.tsx`): six statuses in words, "N of 6
  met" with how many were judged, and on expand each condition's label,
  formula, status and unknown reason with the grade of the setup that judged
  it (`variantFor`: by `setup_version_id`, else scope). URL state: `min`
  (at least N met), `dimension` (must be met), `sort=met|ticker`, `q` (an
  exact ticker opens its card). It ends with `UniverseNote` and the API's
  disclaimer. The stock page's Overview tab adds `ChecklistPanel`
  (`components/checklist/checklist-panel.tsx`), dropped when the call fails.
  Neutral wording only: met / not met / unknown and "N of 6 met", never buy
  or sell words (SEBI note; `tests/unit/checklist.test.tsx` checks). The
  marketing tour's Research panel, the numbers band, the footer, the home
  tiles and /docs/checklist read the same data or describe it. `/recommendations`
  is a `permanentRedirect` to `/checklist` (keeping `q`); `lib/api/recommendations.ts`,
  `signals-table.tsx` and `signals-workspace.ts` are gone. The revalidate tag is
  `checklist`.
- `/news-reactions` (Phase 7.4, Quant Lab nav and subnav, public, 20 views a minute
  per visitor): an event study from the URL (`tickers`, `sentiment`,
  `event_type`, `pre`, `post`) through `getEventStudy()` (`lib/api/research.ts`,
  cached with `bars`/`news` tags), shown by `components/event-study-view.tsx`
  (windows table, mean CAR path as inline SVG, the events; counts only below
  the minimum; "association, not cause"). The stock page's News tab adds a
  "News reactions" block for its negative and positive news (`NewsReactions`).
- `/portfolio?tab=analytics` (Phase 8.1) holds `PortfolioReturnsPanel`
  (`components/portfolio-returns.tsx`): time-weighted return by period and
  money-weighted (XIRR) return for the account and each holding, each with
  its method and basis written beside it and a reason where a figure is
  null. Phase 8.2 adds `PortfolioExposurePanel` (weights by sector,
  country and currency, options delta beside them) and
  `PortfolioAttributionPanel` (price, currency, cross, income per holding)
  from `components/portfolio-exposure.tsx`. Phase 8.3 adds
  `PortfolioRiskPanel` (`components/portfolio-risk.tsx`): VaR/CVaR with the
  rule, window, scenarios and proxies written beside them, and the one-year
  bootstrap percentiles. Its `/v1/portfolio/risk` call runs only while the
  Analytics tab is open (`loadPortfolioData(..., { risk })`). Phase 8.4
  adds `PortfolioStressPanel` (`components/portfolio-stress.tsx`): past
  crises and fixed shocks, each with its change, value after, main drivers,
  and which holdings were proxied or had no history; fetched with the risk
  report (`/v1/portfolio/stress`). The
  metrics strip shows "Unrealized P&L" (equities plus options, #68) and
  lifetime "Realized P&L".
- Pre-trade limits (Phase 8.5): Settings has a "Risk limits" panel
  (`components/risk-limits-form.tsx`, server action, `lib/risk-limits.ts`
  maps empty or invalid fields to no limit). The order review shows
  `LimitPreviewRows` (`components/limit-preview.tsx`) for market and limit
  buys, from `GET /api/limits-check` (a route handler over
  `/v1/portfolio/limits/check`); it is advice only, the API checks again
  when the order fills.
- A0 (25 Nov 2026): the leaderboard, comments and the simulated quote
  badge are gone; Settings keeps display currency, account currency and risk
  limits (`lib/api/profile.ts`). Phase 8.6, UX-9: the
  NAV chart's axis prints the account's currency with grouping
  (`EquityCurve` `currency`, `axisFormatter`), and the metrics strip says
  how each figure is measured (Sharpe names the risk-free rate). The
  Analytics tab adds `RebalancePreview` (`components/rebalance-preview.tsx`,
  whole shares to target weights, nothing placed, each line opens the
  ticket) and a goal form in the Risk panel (`?goal=` on `/portfolio`,
  `goalOdds` puts the chance in words).
- `/status` (Phase 7.6, public, linked from the footer): each nightly job's
  last result and last success, the newest stored close per market, the
  Aegis sync and undeliverable events, from `/v1/status` (`lib/api/status.ts`,
  `no-store`), and (A5.7) a Brokers section. Times in UTC.
- Watchlist rows carry `last_close_at` and `currency`, and alert rows carry
  `currency` (audit RS-13), so the dashboard no longer loads the symbol list
  to format them. `/alerts` still loads it for the create form.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
