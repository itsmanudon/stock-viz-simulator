import { LineChart } from "lucide-react";
import Link from "next/link";

const COLUMNS: { heading: string; links: { href: string; label: string }[] }[] = [
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
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border-muted">
      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1fr_2fr]">
          <div className="max-w-xs">
            <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
              <span className="flex size-7 items-center justify-center rounded-sm border border-brand/40 bg-brand/10 text-brand">
                <LineChart className="size-4" aria-hidden />
              </span>
              StockViz
            </Link>
            <p className="mt-3 text-sm leading-6 text-text-secondary">
              A research and paper-trading workspace built on end-of-day market data.
            </p>
          </div>

          <div className="grid gap-8 sm:grid-cols-3">
            {COLUMNS.map((column) => (
              <nav key={column.heading} aria-label={column.heading}>
                <h2 className="text-2xs font-semibold tracking-[0.12em] text-text-tertiary uppercase">
                  {column.heading}
                </h2>
                <ul className="mt-3 space-y-2">
                  {column.links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className="text-sm text-text-secondary transition-colors hover:text-foreground"
                      >
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        <div className="mt-12 flex flex-col gap-3 border-t border-border-muted pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-text-tertiary">
            © {new Date().getFullYear()} StockViz · v2.0.0-alpha
          </p>
          {/* Not a disclaimer for its own sake: the app simulates fills against
              stored daily closes, and the footer is the one place present on
              every marketing page to say so. */}
          <p className="max-w-xl text-xs leading-5 text-text-tertiary">
            Simulated trading on end-of-day data. Not investment advice, and not a live brokerage —
            prices, fills, and alerts are modelled, not executed on an exchange.
          </p>
        </div>
      </div>
    </footer>
  );
}
