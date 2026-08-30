import { LineChart } from "lucide-react";
import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Website footer for the public pages.
 *
 * Sits on the dark `.panel-inset` ground (squared off, no side borders) so the
 * page ends on a hard stop instead of fading out on the same paper it started
 * on. The palette rebinding that class does means the link columns below can
 * use the ordinary `text-text-secondary` / `border-border-muted` vocabulary
 * and still resolve correctly in either theme.
 */

const COLUMNS: { heading: string; links: { href: string; label: string; external?: boolean }[] }[] =
  [
    {
      heading: "Research",
      links: [
        { href: "/markets", label: "Markets" },
        { href: "/screener", label: "Screener" },
        { href: "/compare", label: "Compare" },
        { href: "/recommendations", label: "Signals" },
        { href: "/news", label: "News" },
      ],
    },
    {
      heading: "Simulation",
      links: [
        { href: "/backtest", label: "Backtest" },
        { href: "/trade", label: "Paper trading" },
        { href: "/portfolio", label: "Portfolio" },
        { href: "/orders", label: "Orders" },
        { href: "/alerts", label: "Price alerts" },
      ],
    },
    {
      heading: "Account",
      links: [
        { href: "/signup", label: "Create account" },
        { href: "/login", label: "Sign in" },
        { href: "/leaderboard", label: "Leaderboard" },
        { href: "/settings", label: "Settings" },
      ],
    },
    {
      heading: "Project",
      links: [
        {
          href: "https://github.com/itsmanudon/stock-viz-simulator",
          label: "Source on GitHub",
          external: true,
        },
      ],
    },
  ];

/**
 * Numbered rather than run together as one grey paragraph. The engine really
 * does simulate fills against stored daily closes, and stating that as
 * discrete, readable notes treats the constraint as part of the product
 * instead of something to bury.
 */
const DISCLOSURES = [
  "Simulated trading only. Orders fill against stored end-of-day closes — this is not a live brokerage and nothing is executed on an exchange.",
  "Not investment advice. Signals are a transparent, rule-based vote count, not a recommendation to buy or sell any security.",
  "Prices, fills, dividends, and alerts are modelled from end-of-day data and will differ from real market outcomes.",
];

export function SiteFooter() {
  return (
    <footer className="panel-inset rounded-none border-x-0 border-b-0">
      <div className="mx-auto w-full max-w-7xl px-4 pt-14 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1fr_2.4fr]">
          <div className="max-w-xs">
            <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
              <span className="flex size-7 items-center justify-center rounded-md border border-brand/40 bg-brand/10 text-brand">
                <LineChart className="size-4" aria-hidden />
              </span>
              StockViz
            </Link>
            <p className="mt-3 text-sm leading-6 text-text-secondary">
              A research and paper-trading workspace built on end-of-day market data.
            </p>
          </div>

          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {COLUMNS.map((column) => (
              <nav key={column.heading} aria-label={column.heading}>
                <h2 className="font-mono text-2xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                  {column.heading}
                </h2>
                <ul className="mt-3 space-y-2">
                  {column.links.map((link) =>
                    link.external ? (
                      <li key={link.href}>
                        <a
                          href={link.href}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm text-text-secondary transition-colors hover:text-foreground"
                        >
                          {link.label}
                        </a>
                      </li>
                    ) : (
                      <li key={link.href}>
                        <Link
                          href={link.href}
                          className="text-sm text-text-secondary transition-colors hover:text-foreground"
                        >
                          {link.label}
                        </Link>
                      </li>
                    ),
                  )}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        <ol className="mt-14 grid gap-x-10 gap-y-4 border-t border-border-muted pt-8 sm:grid-cols-3">
          {DISCLOSURES.map((note, index) => (
            <li key={note} className="flex gap-2.5">
              <span aria-hidden className="font-mono text-2xs text-brand/70 tabular-nums">
                {index + 1}
              </span>
              <p className="text-2xs leading-5 text-text-tertiary">{note}</p>
            </li>
          ))}
        </ol>

        <div className="mt-10 flex flex-col gap-3 border-t border-border-muted pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-mono text-2xs text-text-tertiary">
            © {new Date().getFullYear()} StockViz · v2.0.0-alpha
          </p>
          <ThemeToggle />
        </div>
      </div>

      {/* Closing graphic: the wordmark as hollow display type, clipped by the
          footer's own overflow so it reads as a watermark rather than a title.
          Decorative only — the real wordmark is the link above. */}
      <p
        aria-hidden
        className="text-outline mt-6 -mb-[0.18em] w-full text-center font-semibold tracking-tight select-none [--outline-color:var(--brand)] text-[clamp(4rem,17vw,15rem)] leading-none"
      >
        StockViz
      </p>
    </footer>
  );
}
