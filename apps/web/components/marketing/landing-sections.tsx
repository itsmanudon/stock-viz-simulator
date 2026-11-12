/**
 * Landing sections below the hero (Aurora board v5, SolCard Drops style).
 *
 * Each section has one visual of its own. Data comes from the public API at
 * render time; a section whose data is missing is left out rather than shown
 * empty or with invented figures. Motion is added by `LandingMotion` through
 * `data-motion` markers; every section is complete without it.
 */

import { ArrowRight, CalendarClock, ListChecks, ScrollText, Sparkles, Trophy } from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { loadPhoneScreens } from "@/components/marketing/hero-phone-screens";
import { DecodeText } from "@/components/marketing/proofs/decode-text";
import { type BoardRow, DepartureBoard } from "@/components/marketing/proofs/departure-board";
import { ExplodedCandle } from "@/components/marketing/proofs/exploded-candle";
import { ScrollStory } from "@/components/marketing/scroll-story";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { ApiError, getBars, getMarketsSummary } from "@/lib/api";
import { type LeaderboardEntry, getLeaderboard } from "@/lib/api/leaderboard";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { describeFillRule, formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

async function safe<T>(run: () => Promise<T>): Promise<T | null> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

function SectionHead({
  title,
  soft,
  children,
  center = false,
}: {
  title: string;
  soft?: string;
  children?: ReactNode;
  center?: boolean;
}) {
  return (
    <div
      className={cn("grid max-w-2xl gap-3", center && "mx-auto justify-items-center text-center")}
    >
      <h2
        data-motion="words"
        className="text-3xl font-medium tracking-[-0.03em] text-balance sm:text-4xl lg:text-5xl"
      >
        {title} {soft ? <span className="text-text-tertiary">{soft}</span> : null}
      </h2>
      {children ? (
        <p className="max-w-xl text-base leading-7 text-text-secondary text-pretty">{children}</p>
      ) : null}
    </div>
  );
}

function Wrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24", className)}>
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * Moving at the latest close: the biggest one-day moves, as tinted cards.
 */
export async function MovingToday() {
  const summary = await safe(() => getMarketsSummary({ sparklineDays: 30 }));
  const rows = (summary?.rows ?? [])
    .filter((row) => row.change_pct !== null && row.last_close !== null && row.closes.length > 1)
    .sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0))
    .slice(0, 5);
  if (rows.length < 2) return null;
  // Symbols can have different latest closes, so each card is dated by its
  // own stored bar rather than one date for the whole row (UI audit T1).
  const dates = await Promise.all(
    rows.map(async (row) => {
      const bars = await safe(() => getBars(row.ticker, { limit: 1 }));
      return formatCloseDate(bars?.[0]?.ts);
    }),
  );

  return (
    <Wrap>
      <div className="flex flex-wrap items-end justify-between gap-6">
        <SectionHead title="Moving at the latest close.">
          The biggest one-day moves in the tracked universe, each at its latest stored close. Each
          card opens the stock page.
        </SectionHead>
        <Button asChild variant="outline" className="glass rounded-full px-5">
          <Link href="/markets">Open markets</Link>
        </Button>
      </div>
      <ul
        data-motion="rise"
        className="mt-10 grid snap-x snap-mandatory auto-cols-[minmax(13.5rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-3"
      >
        {rows.map((row, index) => {
          const up = (row.change_pct ?? 0) >= 0;
          const tone = up ? "var(--positive)" : "var(--negative)";
          return (
            <li
              key={row.ticker}
              data-motion-item
              style={{ "--tone": tone } as CSSProperties}
              className="relative grid snap-start justify-items-center gap-3 rounded-3xl border border-border-muted bg-[radial-gradient(120%_70%_at_50%_0%,color-mix(in_oklab,var(--tone)_16%,var(--card)),var(--background)_75%)] p-5 text-center focus-within:ring-2 focus-within:ring-ring"
            >
              <span
                className={cn(
                  "rounded-full px-2.5 py-0.5 font-mono text-xs",
                  up
                    ? "bg-positive-soft text-positive-soft-foreground"
                    : "bg-negative-soft text-negative-soft-foreground",
                )}
              >
                <DecodeText
                  text={`${up ? "▲ +" : "▼ "}${(row.change_pct ?? 0).toFixed(2)}%`}
                  delay={index * 0.12}
                />
              </span>
              <span className="text-xl font-medium tracking-tight">{row.ticker}</span>
              <span className="-mt-2 line-clamp-1 text-xs text-text-tertiary">{row.name}</span>
              <Sparkline
                closes={row.closes.map(Number)}
                showBaseline
                className="h-16 w-full"
                periodLabel={`${row.closes.length}-session`}
              />
              <span className="flex w-full justify-between text-xs text-text-tertiary">
                {dates[index] ? `Close · ${dates[index]}` : "Close"}
                <span className="font-mono text-foreground" data-financial>
                  <DecodeText
                    text={formatCurrency(row.last_close, row.currency)}
                    delay={0.3 + index * 0.12}
                  />
                </span>
              </span>
              <Link
                href={`/stocks/${encodeURIComponent(row.ticker)}`}
                aria-label={`Research ${row.ticker}`}
                className="w-full rounded-full bg-primary py-2 text-sm font-medium text-primary-foreground after:absolute after:inset-0 after:rounded-3xl focus-visible:outline-none"
              >
                Research
              </Link>
            </li>
          );
        })}
      </ul>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * How a session works: three tiles, each with a small looping illustration.
 * The illustrations carry no figures, so nothing in them can be mistaken for
 * data. Their CSS loops stop with reduced motion.
 */
export function SessionTiles() {
  const tiles = [
    {
      title: "Screen.",
      body: "Filter the tracked universe down to the handful worth a look.",
      art: (
        <div className="grid w-full gap-1.5">
          <div className="flex justify-center gap-1.5 font-mono text-3xs">
            <span className="rounded-full bg-primary px-2 py-0.5 text-primary-foreground">
              RSI &lt; 30
            </span>
            <span className="rounded-full border border-border-muted px-2 py-0.5">Volume ↑</span>
            <span className="rounded-full border border-border-muted px-2 py-0.5">NSE</span>
          </div>
          {[92, 74, 60, 84, 68].map((width, index) => (
            <span
              key={width}
              className={cn(
                "flex h-7 items-center gap-2 rounded-lg border border-border-muted bg-surface-secondary px-2.5",
                index >= 3 && "landing-filter-out",
              )}
              style={{ animationDelay: `${(index - 3) * 0.2}s` }}
            >
              <span className="size-2 rounded-full bg-text-tertiary" />
              <span className="h-1.5 rounded-full bg-border" style={{ width: `${width}%` }} />
            </span>
          ))}
        </div>
      ),
    },
    {
      title: "Simulate.",
      body: "Every order opens a review first: price, its date, cost and the fill rule.",
      art: (
        <div className="landing-slide-up grid w-[85%] gap-1.5 rounded-t-2xl border border-b-0 border-border bg-surface-secondary p-3 text-left">
          <span className="text-3xs tracking-[0.14em] text-text-tertiary">REVIEW ORDER</span>
          <span className="h-3 w-2/3 rounded-full bg-foreground/80" />
          <span className="flex justify-between text-3xs text-text-tertiary">
            Reference close <span className="h-1.5 w-12 self-center rounded-full bg-border" />
          </span>
          <span className="flex justify-between text-3xs text-text-tertiary">
            Fees <span>None</span>
          </span>
          <span className="mt-1 rounded-full bg-primary py-1.5 text-center text-2xs font-medium text-primary-foreground">
            Place buy order
          </span>
        </div>
      ),
    },
    {
      title: "Keep score.",
      body: "Your value, history and journal show what each decision was worth.",
      art: (
        <svg viewBox="0 0 260 120" className="h-32 w-full" aria-hidden="true">
          <path
            className="landing-draw"
            d="M6 104 C 30 98, 42 80, 62 84 S 96 96, 112 70 S 150 62, 166 48 S 200 56, 214 34 S 244 22, 254 12"
            fill="none"
            stroke="var(--brand-gradient-to)"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
        </svg>
      ),
    },
  ];
  return (
    <Wrap>
      <SectionHead title="How a session works." soft="Screen it. Simulate it. Keep score." center />
      <ul data-motion="rise" className="mt-12 grid gap-3 md:grid-cols-3">
        {tiles.map((tile) => (
          <li
            key={tile.title}
            data-motion-item
            className="relative grid min-h-80 grid-rows-[auto_auto_1fr] gap-2 overflow-hidden rounded-3xl border border-border-muted bg-linear-to-b from-card to-background p-5"
          >
            <h3 className="text-lg font-medium">{tile.title}</h3>
            <p className="text-sm leading-6 text-text-tertiary">{tile.body}</p>
            <div aria-hidden className="relative grid place-items-end justify-items-center pt-4">
              <div className="brand-glow -bottom-20 h-36 w-64 opacity-50" />
              <div className="relative grid w-full justify-items-center">{tile.art}</div>
            </div>
          </li>
        ))}
      </ul>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * Every fill shows its work: three steps, lit in turn as the section scrolls.
 */
export function FillSteps() {
  const steps = [
    {
      icon: CalendarClock,
      title: "A dated close",
      body: "Every price names the close it comes from, with its date and exchange.",
    },
    {
      icon: ListChecks,
      title: "A stated fill rule",
      body: `${describeFillRule("market")}. ${describeFillRule("limit")}.`,
    },
    {
      icon: ScrollText,
      title: "A kept record",
      body: "Each fill is saved with the close and the rule it used, so your history and replays can be checked later.",
    },
  ];
  return (
    <Wrap>
      <SectionHead title="Every fill shows its work." soft="Nothing happens off screen.">
        StockViz states how an order fills before you place it, and keeps the record afterwards.
      </SectionHead>
      <div data-motion="steps" className="mt-12">
        <div
          aria-hidden
          className="mb-5 grid grid-cols-[auto_1fr_auto_1fr_auto] items-center gap-3"
        >
          {steps.map((step, index) => [
            <span
              key={step.title}
              data-step={index}
              data-step-pill
              data-on="true"
              className="rounded-full border border-border px-3 py-1 text-xs text-text-tertiary transition-colors data-[on=true]:border-primary data-[on=true]:bg-primary data-[on=true]:text-primary-foreground"
            >
              Step {index + 1}
            </span>,
            index < steps.length - 1 ? (
              <span
                key={`${step.title}-line`}
                data-step-line
                className="relative h-px overflow-hidden bg-border after:absolute after:inset-0 after:origin-left after:[transform:scaleX(var(--p,1))] after:bg-linear-to-r after:from-brand-gradient-from after:to-brand-gradient-via"
              />
            ) : null,
          ])}
        </div>
        <ol className="grid gap-4 md:grid-cols-3">
          {steps.map((step, index) => {
            const Icon = step.icon;
            return (
              <li key={step.title}>
                <div
                  data-step={index}
                  data-on="true"
                  className="group grid h-44 place-items-center rounded-2xl border border-border-muted bg-card transition-colors data-[on=true]:bg-[radial-gradient(90%_70%_at_50%_110%,color-mix(in_oklab,var(--brand-gradient-from)_45%,transparent),var(--card)_70%)]"
                >
                  <span className="grid size-20 place-items-center rounded-full border border-border text-text-tertiary transition-all group-data-[on=true]:border-transparent group-data-[on=true]:bg-[radial-gradient(circle_at_35%_30%,var(--brand-gradient-to),var(--brand-gradient-via)_45%,var(--brand-gradient-from))] group-data-[on=true]:text-white group-data-[on=true]:shadow-[0_0_40px_color-mix(in_oklab,var(--brand-gradient-via)_55%,transparent)]">
                    <Icon className="size-8" aria-hidden />
                  </span>
                </div>
                <h3 className="mt-4 text-base font-medium">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-6 text-text-tertiary">{step.body}</p>
              </li>
            );
          })}
        </ol>
      </div>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * Statement band.
 */
export function StatementBand() {
  return (
    <Wrap className="py-8 sm:py-12">
      <div className="relative isolate grid justify-items-center gap-6 overflow-hidden rounded-[2rem] border border-border-muted bg-card px-6 py-20 text-center">
        <span
          aria-hidden
          data-motion="glow"
          className="absolute -bottom-1/2 left-1/2 -z-10 h-full w-[120%] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--brand-gradient-to)_55%,transparent),color-mix(in_oklab,var(--brand-gradient-from)_45%,transparent)_50%,transparent)] blur-2xl"
        />
        <h2
          data-motion="words"
          className="max-w-3xl text-3xl font-medium tracking-[-0.03em] text-balance sm:text-5xl"
        >
          No hidden fills.{" "}
          <span className="text-text-tertiary">Every trade shows the close it used.</span>
        </h2>
        <Button asChild size="lg" className="rounded-full px-6">
          <Link href="/replay" className="gap-2">
            Replay a past session
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </div>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * Rankings: the public leaderboard. Only people who chose a public profile
 * appear (the API enforces it), and the section is left out when none do.
 */
/** A trader's name as it fits on the board: whole if it fits, else "AVA L". */
function boardName(name: string) {
  if (name.length <= 12) return name;
  const [first, ...rest] = name.split(" ");
  const initial = rest[0]?.[0];
  return initial ? `${first.slice(0, 10)} ${initial}` : name.slice(0, 12);
}

export async function Rankings() {
  const entries = (await safe(() => getLeaderboard())) ?? [];
  const top = entries.slice(0, 5);
  if (top.length === 0) return null;
  const byReturn: BoardRow[] = top.map((entry) => ({
    rank: String(entry.rank),
    name: boardName(entry.username),
    value: `${entry.return_pct >= 0 ? "+" : ""}${entry.return_pct.toFixed(2)}%`,
    tone: entry.return_pct > 0 ? "pos" : entry.return_pct < 0 ? "neg" : "none",
  }));
  const byValue: BoardRow[] = [...top]
    .sort((a, b) => Number(b.portfolio_value) - Number(a.portfolio_value))
    .map((entry, index) => ({
      rank: String(index + 1),
      name: boardName(entry.username),
      value: `$${Math.round(Number(entry.portfolio_value)).toLocaleString("en-US")}`,
      tone: "none",
    }));
  return (
    <Wrap>
      <SectionHead title="Real paper." soft="Real rankings." center>
        The public leaderboard, ranked by return on the same paper start.
      </SectionHead>
      {/* The board is a picture of the list below it; the list is what a
          screen reader reads, in the board's first order. */}
      <div
        className="relative mx-auto mt-10 w-full max-w-3xl overflow-hidden rounded-3xl border border-border-muted bg-card"
        style={{ height: `${4.5 + top.length * 2.4}rem` }}
      >
        <DepartureBoard
          boards={[
            { title: "BY RETURN", rows: byReturn },
            { title: "BY VALUE", rows: byValue },
          ]}
        />
      </div>
      <ol className="sr-only">
        {top.map((entry: LeaderboardEntry) => (
          <li key={entry.user_id}>
            Rank {entry.rank}: {entry.username}, {entry.return_pct >= 0 ? "up" : "down"}{" "}
            {Math.abs(entry.return_pct).toFixed(2)}%, account value{" "}
            {formatCurrency(entry.portfolio_value, "USD")}
          </li>
        ))}
      </ol>
      <p className="mt-4 text-center">
        <Link
          href="/leaderboard"
          className="text-sm text-text-secondary underline-offset-4 hover:underline"
        >
          See the full leaderboard
        </Link>
      </p>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * FAQ. Answers describe what the product does today, nothing planned.
 */
const FAQ = [
  {
    q: "Is any of this real money?",
    a: "No. Every account starts with $100,000 of paper money. Nothing is sent to a broker or an exchange.",
  },
  {
    q: "Where do the prices come from?",
    a: "Stored end-of-day closes for US and Indian listings, refreshed once a day after the close. They are not live quotes, and prices say which close they are.",
  },
  {
    q: "How does an order fill?",
    a: `${describeFillRule("market")}. ${describeFillRule("limit")}.`,
  },
  {
    q: "Are the signals advice?",
    a: "No. Signals are a seven-rule vote you can read line by line, including the rules that failed.",
  },
  {
    q: "Who appears on the leaderboard?",
    a: "Only people who chose to make their profile public. You can change that in Settings at any time.",
  },
];

/**
 * How to read a candle, beside the FAQ: one stored daily bar taken apart
 * (motion batch 3). The caption states the same four prices in text.
 */
async function FaqCandle() {
  for (const ticker of ["NVDA", "AAPL", "MSFT"]) {
    const bars = await safe(() => getBars(ticker, { limit: 1 }));
    const bar = bars?.[0];
    if (!bar) continue;
    const values = {
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    };
    if (!(values.high > values.low)) continue;
    const f = (v: number) => v.toFixed(2);
    return (
      <figure className="mt-4 grid gap-2">
        <div className="relative aspect-[16/9] w-full max-w-md overflow-hidden rounded-2xl border border-border-muted bg-card">
          <ExplodedCandle bar={values} />
        </div>
        <figcaption className="font-mono text-2xs leading-5 text-text-tertiary">
          How to read a candle: {ticker}, {formatCloseDate(bar.ts)}. Open {f(values.open)}, high{" "}
          {f(values.high)}, low {f(values.low)}, close {f(values.close)}.
        </figcaption>
      </figure>
    );
  }
  return null;
}

export function LandingFaq() {
  return (
    <Wrap>
      <div className="grid gap-10 md:grid-cols-[0.8fr_1.2fr] md:items-start">
        <div className="grid gap-3">
          <h2 data-motion="words" className="text-4xl font-medium tracking-[-0.03em] sm:text-5xl">
            Paper trading, made plain.
          </h2>
          <p className="flex items-center gap-2 text-text-secondary">
            <Sparkles className="size-4 text-brand" aria-hidden />
            What people ask before they open an account.
          </p>
          <FaqCandle />
        </div>
        <div className="grid gap-2">
          {FAQ.map((item, index) => (
            <details
              key={item.q}
              open={index === 0}
              className="group rounded-2xl border border-border-muted bg-card px-4 py-3.5"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-medium [&::-webkit-details-marker]:hidden">
                {item.q}
                <span aria-hidden className="text-text-tertiary group-open:hidden">
                  +
                </span>
                <span aria-hidden className="hidden text-text-tertiary group-open:inline">
                  −
                </span>
              </summary>
              <p className="mt-2.5 text-sm leading-6 text-text-tertiary">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </Wrap>
  );
}

/* ---------------------------------------------------------------------------
 * Scroll story, with the same screens as the hero phone.
 */
export async function StorySection() {
  const screens = await loadPhoneScreens();
  return <ScrollStory screens={screens} />;
}
