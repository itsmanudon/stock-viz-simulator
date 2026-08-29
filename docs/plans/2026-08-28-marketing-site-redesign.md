# Marketing site redesign — plan

**Scope:** `apps/web/app/(public)/page.tsx`, `components/public-header.tsx`,
`components/site-footer.tsx`, plus new `components/marketing/*` and a small
number of token/motion additions in `app/globals.css`.

**Goal:** make the public surface read as a serious, modern research product
instead of a generic feature grid — without breaking the repo's honesty rule
(end-of-day data, simulated fills, rule-based signals; no invented social
proof).

---

## 0. Diagnosis of the current page

Read `app/(public)/page.tsx` (214 lines) against the reference board below and
five concrete problems fall out:

1. **The hero never shows the product.** It is centered text + two buttons.
   Every reference that works — Public, Sprig, Linear, Monarch — puts real UI
   in the first viewport. We have the best possible asset for this (`TopMovers`
   renders *live data from our own API*) and we bury it in a separate section
   under a 14px heading.
2. **One rhythm for the whole page.** Five sections, all `max-w-7xl`,
   all `py-16 sm:py-20`, all on `--background` except one `bg-surface-secondary/40`
   band. Nothing establishes hierarchy, so nothing feels designed.
3. **The feature section is the weakest available pattern.** A 3×2 grid of
   `size-9` icon + title + paragraph. It tells; it never shows. Linear, V7,
   Framer and Maze all use *tabbed or scroll-synced panels containing real
   interface*.
4. **No proof of substance.** No numbers, no data band, no "here is the actual
   ruleset". For a product whose whole pitch is transparency, that is a miss.
5. **Zero motion and zero texture.** No scroll reveal, no gradient, no grid, no
   hover state beyond a color swap. The 2026 baseline for "sleek" is
   *restrained* motion, but it is not *no* motion.

The brand itself is **not** the problem. The ATLAS palette (warm paper
`#f7f6f2` + `#96702b` gold, dark `#0f1112` + `#d5b36a`) with Space Grotesk /
JetBrains Mono is genuinely distinctive — most fintech sites in the reference
board are blue-on-white or black-on-black. The plan leans *into* it rather than
replacing it.

---

## 1. Reference board

Pulled from Mobbin and the live sites. Each entry lists the one thing to take.

### Hero

| Reference | Take |
| --- | --- |
| [Public — "Invest in stocks"](https://mobbin.com/sites/sections/053b4775-654d-4e70-b8fb-316c795156cc) | Asymmetric split: copy left, a single dramatic product visual right on a dark inset panel. The panel does the work; the copy stays short. |
| [Public — "Investing for those who take it seriously"](https://mobbin.com/sites/sections/75be0f10-fcff-4737-b708-5712ed21af17) | Serif display headline + a row of tiny icon+label "proof chips" under it, CTA pushed to the right. The chips are where hard constraints can live honestly. |
| [Sprig / Coinvest](https://mobbin.com/sites/sections/2ebc7ddd-564a-462e-9c84-8265a0c89762) | Full app chrome (sidebar + ticker + chart) cropped at the bottom of the hero, bleeding off-screen. Reads as "this is a real workspace". |
| [Linear](https://linear.app/) | Hero visual is the *actual app* at high fidelity, not a mockup. Also: an eyebrow pill that links to a real changelog entry. |
| [Origin — "A single place to grow your wealth"](https://mobbin.com/sites/sections/3d3d782f-ef8d-49b5-89ab-0f0ea0d89f61) | Full-bleed single-color hero with a mono uppercase eyebrow. Proof that one confident color beats a gradient. |

### Feature demonstration

| Reference | Take |
| --- | --- |
| [Framer](https://mobbin.com/sites/sections/556c62ee-b2af-4993-b400-187d98f1fd72) | Icon-label tab row above one large canvas that swaps. Cheap to build, reads as a product tour. |
| [V7 — "See it in action"](https://mobbin.com/sites/sections/21fe2a46-81f1-47f6-8b59-ff0183825c9f) | Two-tone headline (solid + muted second line), one framed screenshot, a **breadcrumb-style step rail underneath** (`Dataset › Consensus › Logic › Complete`). Maps perfectly onto our Screen → Test → Trade → Track loop. |
| [Maze](https://mobbin.com/sites/sections/2aab052c-921a-421b-a4a0-5aa155ebe09c) | Tab chips sit *inside* the colored panel, not above it. Contains the whole demo in one object. |
| [Ada](https://mobbin.com/sites/sections/9b10b8f3-262e-497f-9d9a-6dabc7e14593) | Vertical pill stack as the selector, with copy on one side and the visual on the other. Good for a 6-item list like ours. |
| [Zipline](https://mobbin.com/sites/sections/ce7e2b2b-54f9-4a13-952e-4a895a0f7c30) | Hotspot annotations pinned onto the visual. Directly applicable to explaining the 7-vote signal panel. |

### Goal / outcome display

| Reference | Take |
| --- | --- |
| [Resend](https://mobbin.com/sites/sections/b35011ab-ad11-4671-82db-c8d722383d20) | Label *above*, huge number below, thin rules between columns, and a footnote — "Real-time data from the past 30 days". Exactly the honest register we need. |
| [Glide](https://mobbin.com/sites/sections/979fe5b7-85d8-450e-8b61-5534ff3f1f97) | Stats as full-width stacked rows with a horizontal rule between each, number left / explanation right. Far more editorial than a 3-up card grid. |
| [Revolut](https://mobbin.com/sites/sections/b5d03099-8332-47e5-bd72-ed80d0d9756b) | Blunt section title ("Let's run the numbers") + three bordered tiles on near-black. |
| [Public — About](https://mobbin.com/sites/sections/703b5144-adf5-4b4d-822a-26e868238bb2) | Mission statement as a centered two-line serif sentence with a soft radial glow behind it. |
| [Ramp](https://www.ramp.com/) | Outcomes are quantified *per use case*, not as vanity totals. |

### Footer

| Reference | Take |
| --- | --- |
| [ReadMe](https://mobbin.com/sites/sections/d397cd49-0a96-477b-aff0-dec8694a2b49) | Oversized outlined wordmark as the closing graphic, on a faint blueprint grid. Zero content cost, huge finish. |
| [1Password](https://mobbin.com/sites/sections/2f98f04c-02a7-4495-9fd2-f5be12137aac) | Giant logo lockup under the link columns; legal row sits below on its own line. |
| [Slash](https://mobbin.com/sites/sections/11bef592-05db-4c10-9750-54e83f0a7fe8) | Numbered legal/disclosure footnotes as a deliberate typographic block. Fintech-native; makes disclosure look like rigor, not liability. |
| [Corgi](https://mobbin.com/sites/sections/63e60bfc-1a20-41d0-a3b3-2da8a43a3723) | A full-bleed illustration *between* the links and the disclaimer. |
| [Vanta](https://mobbin.com/sites/sections/15f32198-9410-4592-add8-a95d08db61ef) | Footer on an inverted dark surface, detached from page background. |

### Trend notes (2026)

From the design-press sweep: dark mode as a *defining* rather than optional
mode; **compliance and disclosure surfaced as design elements** rather than
buried; single-conviction brand aesthetics executed at every scale; quantified
outcomes over adjectives. All four favour this repo's existing posture.

Sources: [Ballistic Media](https://www.ballistic.media/blog/fintech-website-designs),
[Azuro Digital](https://azurodigital.com/fintech-website-examples/),
[Webstacks](https://www.webstacks.com/blog/fintech-websites).

---

## 2. Art direction

**One conviction: "the terminal, on paper."** Warm ATLAS paper as the ground,
gold reserved strictly for identity/focus/selected, JetBrains Mono used as a
*structural* device (eyebrows, stat labels, step numbers, ticker data) rather
than decoration, and a single dark inset panel per major section that holds the
product UI. Positive/negative stay their own semantic hues so a price never
reads like a button.

Three rules that keep it coherent:

1. **Gold is never a background fill for a large area.** Panel, rule, chip
   border, focus ring, one CTA. That's it.
2. **Every product visual sits in a dark, rounded, `--surface-elevated` panel
   with a 1px hairline** — even in light mode. This becomes the page's
   signature object and gives light mode the contrast it currently lacks.
3. **Section rhythm alternates:** paper → dark inset → paper → full-bleed band
   → paper → dark footer. No two consecutive sections share a ground.

---

## 3. Section-by-section spec

### 3.1 Header — `components/public-header.tsx`

- Keep sticky, but make it a **floating pill** at `top-3` (`rounded-full
  border bg-background/70 backdrop-blur-xl`) that only gains its border and
  shadow after ~24px of scroll (`useScroll` + a `data-scrolled` attribute).
  Cheap, and it is the single strongest "modern" signal in the header.
- Add a **live market-status chip** on the left of the CTA: a 6px dot
  (`--positive` pulsing when the last bar is today, `--text-tertiary`
  otherwise) + `EOD · 27 AUG` in mono `text-2xs`. This is honest, it is real
  data, and no competitor has it.
- Nav gains an underline that animates from center on hover
  (`after:` pseudo, `scale-x` transition).
- Mobile: keep `MobileNav`, restyle the sheet to match the pill.

### 3.2 Hero — `components/marketing/hero.tsx`

Layout: asymmetric `lg:grid-cols-[minmax(0,1fr)_1.15fr]`, left copy / right
panel — the Public + Sprig pattern.

**Left:**
- Eyebrow becomes a **linked pill**, Linear-style: `New · Options settlement →`
  linking to `/trade`. Mono, `text-2xs`, tracking `0.16em`, gold border at 40%.
- H1 stays `Learn the market without risking the money` (it is good) but goes
  to `text-5xl lg:text-7xl` with the existing `--text-6xl` tracking, and the
  second clause gets `text-text-secondary` — the V7 two-tone treatment.
- Subhead trimmed to ~20 words. Current one is 34 and buries the verb.
- CTA row unchanged (`Create free account` / `Explore markets`).
- **Replace the fine-print line with three proof chips** (icon + mono label):
  `No card required` · `500+ symbols` · `Simulated fills, EOD data`. The
  disclosure becomes a design element instead of grey apology text.

**Right — the signature panel:**
- Dark `--surface-elevated` panel, `rounded-xl`, hairline border, subtle
  gold radial glow behind it (`radial-gradient` blob at 12% opacity, hidden
  under `prefers-reduced-motion` only if animated).
- Inside: a **cropped, non-interactive replica of the workspace** — a mini
  sidebar rail, a ticker header with a live-looking price, an area chart
  (reuse `components/sparkline.tsx` scaled up, or `equity-curve.tsx`), and a
  positions strip. Server-rendered from the same `getBars` / `listSymbols`
  calls `TopMovers` already makes, so it shows *real* AAPL/NVDA data.
- Panel bleeds `overflow-hidden` past the right edge on `lg:` — Sprig's crop.

**Below the fold seam:** the existing `TopMovers` becomes a **full-bleed
horizontal marquee ticker strip** directly under the hero — mono, tabular-nums,
`border-y`, auto-scrolling with `animation-play-state: paused` on hover and
disabled under `prefers-reduced-motion`. This is the highest-value change on
the page: it is live data, it is instantly legible as "stock market", and it
costs one component.

> Keep the existing graceful-degradation behaviour from `top-movers.tsx` — a
> `—` placeholder on missing quotes, empty state on `ApiError`. A freshly
> seeded DB must not break the hero.

### 3.3 Feature demonstration — `components/marketing/product-tour.tsx`

Replace the 3×2 icon grid entirely. Build the **Framer/Maze tabbed canvas**:

- A row of 4 mono tab chips inside the panel: `SCREEN` · `RESEARCH` ·
  `SIMULATE` · `TRACK`.
- One large dark panel below that swaps content per tab, each showing a real
  cropped screenshot or a lightweight recreation:
  - **SCREEN** — screener filter rail + result rows (RSI, momentum, 52w).
  - **RESEARCH** — the 7-vote signal panel with **Zipline-style hotspot
    annotations** pointing at two individual votes. This is the money shot:
    the product's differentiator is that every vote is visible.
  - **SIMULATE** — backtest equity curve + summary stats.
  - **TRACK** — portfolio positions with P&L and the allocation donut.
- Under the panel, a **V7 breadcrumb rail**: `Screen › Research › Simulate ›
  Track`, with the active step in gold. This absorbs the current "How a
  session usually goes" section — the two are the same story told twice.
- Tabs are a client component (`"use client"`), keyboard-navigable
  (`role="tablist"`, arrow keys), auto-advance every 6s until first user
  interaction, and never auto-advance under `prefers-reduced-motion`.
- Keep the six existing `FEATURES` entries, but demote them to a **compact
  link row** under the tour (`Markets · Screener · Signals · Backtest · Trade ·
  Portfolio`) rather than six paragraph cards.

Screenshots: capture at 2× from `pnpm stack:up` with the demo seed
(`pnpm stack:seed`), in **both themes**, save under `docs/images/marketing/`,
serve via `next/image` with explicit `width`/`height` and `priority` only on
the first tab.

### 3.4 Goal display — `components/marketing/by-the-numbers.tsx`

This is the section that is missing entirely today. Use the **Resend/Glide**
treatment on a full-bleed dark band:

- Section label in mono: `WHAT'S ACTUALLY IN HERE`.
- Three to four stacked rows, thin rule between each, **number left in
  `text-5xl` tabular-nums, explanation right in `text-sm`**.
- **Every number must be real and server-fetched**, not hardcoded:
  `listSymbols().length` symbols tracked · bars stored · earliest bar date as
  "history depth" · number of signal votes (7, fixed and honest).
- A Resend-style footnote under the rows in `text-2xs text-text-tertiary`:
  *"Counts read live from the API at page build. End-of-day bars only."*

If an API call fails, the section renders **nothing** rather than a zero — a
`0` here is worse than absence.

> Deliberately **no** logo wall, **no** testimonials, **no** "trusted by N
> traders". The repo's guides forbid overselling, and fabricated social proof
> is the fastest way to make a good site look fake.

### 3.5 Closing CTA — `components/marketing/closing-cta.tsx`

- Keep the copy (`Start with $100,000 that isn't real` is strong).
- Put it on a **full-bleed gold-tinted panel** (`--brand-muted` in light,
  `--brand-muted` dark) with a large faint outlined `$100,000` set in mono
  behind the heading at ~6% opacity — the ReadMe oversized-wordmark trick
  applied to a number.
- Two CTAs unchanged.

### 3.6 Footer — `components/site-footer.tsx`

- Move to an **inverted dark surface** (Vanta) so the page ends on a hard stop.
- Keep the three link columns; add a fourth: `Project` — GitHub, Roadmap,
  Known limitations, API health.
- Add the **oversized outlined `StockViz` wordmark** below the columns
  (ReadMe/1Password) — `text-[clamp(4rem,14vw,11rem)]`, transparent fill,
  1px `--border` stroke via `-webkit-text-stroke`, `select-none aria-hidden`.
- Restyle the existing disclaimer as **numbered disclosure notes** (Slash):
  `1. Simulated fills…` `2. Not investment advice…` `3. Signal votes are
  rule-based…`. Same content, reads as rigor.
- Bottom row: copyright, version, theme toggle, API status dot.

---

## 4. Design system additions

In `app/globals.css` (`@theme inline` and `@layer base`) — additive only, no
existing token changes:

```
--marketing-panel        dark inset panel bg (light: #1b1e20, dark: #17191b)
--marketing-panel-border hairline on the panel
--marketing-glow         gold radial, 12% alpha
--grid-line              blueprint grid stroke for footer/hero backdrop
```

Plus three utilities:

- `.panel-inset` — the signature panel (bg, border, radius-xl, overflow-hidden).
- `.grid-backdrop` — repeating-linear-gradient blueprint grid, masked with a
  radial `mask-image` so it fades at the edges.
- `.marquee` — the ticker animation, with the `prefers-reduced-motion` block
  already in `globals.css` covering the disable case (verify it does — the
  existing block sets `animation-duration: 0.01ms`, which is sufficient).

**Motion primitive:** one `components/marketing/reveal.tsx` client component
wrapping `IntersectionObserver` → `opacity 0→1, translateY 12px→0, 400ms
cubic-bezier(0.16,1,0.3,1)`, staggered by index. Do **not** add Framer Motion;
this is ~30 lines and the repo has no animation dependency today.

---

## 5. Implementation phases

Each phase is independently shippable and leaves the page working.

| Phase | Work | Files |
| --- | --- | --- |
| **1 — Foundation** | Tokens, `.panel-inset`, `.grid-backdrop`, `Reveal`, `components/marketing/` scaffold | `app/globals.css`, `components/marketing/reveal.tsx` |
| **2 — Hero + ticker** | New hero, hero product panel, `TopMovers` → marquee | `app/(public)/page.tsx`, `components/marketing/hero.tsx`, `components/marketing/hero-panel.tsx`, `components/top-movers.tsx` |
| **3 — Header** | Floating pill, scroll state, market-status chip, nav underline | `components/public-header.tsx`, `components/marketing/market-status.tsx` |
| **4 — Product tour** | Tabbed canvas, hotspots, step rail; delete `FEATURES` grid + `STEPS` section | `components/marketing/product-tour.tsx`, `docs/images/marketing/*` |
| **5 — Numbers** | Live stats band | `components/marketing/by-the-numbers.tsx`, `lib/api/markets.ts` (may need a count) |
| **6 — CTA + footer** | Gold panel CTA, dark footer, outlined wordmark, numbered disclosures | `components/marketing/closing-cta.tsx`, `components/site-footer.tsx` |
| **7 — Polish** | Reduced-motion audit, Lighthouse, both themes at 320/768/1440, e2e update | `apps/web/e2e/*` |

Ship 1–3 as one PR (`feat/marketing-hero`), 4–5 as a second
(`feat/marketing-tour`), 6–7 as a third (`feat/marketing-footer`). All target
`dev`.

---

## 6. Constraints and risks

- **Honesty rule (from `CLAUDE.md`).** Copy must stay literal about end-of-day
  data, simulated fills, and rule-based (not AI) signals. The redesign
  *increases* disclosure surface (proof chips, stat footnote, numbered notes) —
  do not let visual polish erode it, and do not invent social proof.
- **Server components.** The hero panel, ticker, and stats band all fetch from
  the API at request/build time. Every one needs the `ApiError` fallback
  `top-movers.tsx` already models, or a cold DB breaks the landing page.
- **Images.** Four tour screenshots × 2 themes × 2× DPR is the main weight
  budget. Use `next/image`, AVIF/WebP, explicit dimensions, and lazy-load
  every tab after the first. Target: hero LCP unchanged or better.
- **Reduced motion.** Marquee, auto-advancing tabs, reveal, and the header
  transition all need to no-op under `prefers-reduced-motion`. The global
  block in `globals.css` covers CSS animation but **not** the JS auto-advance
  timer — gate that with `matchMedia` explicitly.
- **Accessibility.** Tour tabs need real `role="tablist"`/`aria-selected` and
  arrow-key handling. The marquee needs `aria-hidden` on the duplicated track.
  The outlined wordmark is decorative — `aria-hidden`, `select-none`.
- **Both themes are load-bearing.** The dark panel on paper is the whole idea;
  verify it does not turn into a dark-on-dark mush in dark mode (that is why
  the panel uses `--surface-elevated`, one step above `--card`).
- **Guides.** Per the repo rule, update `apps/web/CLAUDE.md` in the same PR
  that adds `components/marketing/`.
