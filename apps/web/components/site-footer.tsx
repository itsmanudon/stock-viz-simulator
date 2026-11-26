import Link from "next/link";
import { Suspense } from "react";

import rootPackage from "../../../package.json";

import { StockVizWordmark } from "@/components/brand/stockviz-mark";
import { FooterCloseLine, FooterStatus } from "@/components/footer-market";
import { ChromeWordmark } from "@/components/prism/chrome-wordmark";
import { titleCase } from "@/lib/title-case";

/**
 * Website footer for the public pages.
 *
 * Sits on the neutral `.panel-inset` ground (squared off, no side borders) so the
 * page ends on a hard stop instead of fading out on the same paper it started
 * on. The palette rebinding that class does means the link columns below can
 * use the ordinary `text-text-secondary` / `border-border-muted` vocabulary
 * and still resolve correctly in either theme.
 */

const COLUMNS: { heading: string; links: { href: string; label: string; external?: boolean }[] }[] =
  [
    {
      heading: "Product",
      links: [
        { href: "/product/paper-trading", label: "Paper trading" },
        { href: "/product/research", label: "Research" },
        { href: "/product/replay", label: "Replay" },
        { href: "/docs", label: "Docs" },
      ],
    },
    {
      heading: "Research",
      links: [
        { href: "/markets", label: "Markets" },
        { href: "/screener", label: "Screener" },
        { href: "/compare", label: "Compare" },
        { href: "/checklist", label: "Checklist" },
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
        { href: "/settings", label: "Settings" },
        { href: "/status", label: "Status" },
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
  "Not investment advice. The Checklist counts six published conditions per symbol; it is not a recommendation to buy or sell any security.",
  "Prices, fills, dividends, and alerts are modelled from end-of-day data and will differ from real market outcomes.",
];

export function SiteFooter() {
  return (
    <footer className="site-footer panel-inset rounded-none border-x-0 border-b-0 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] sm:pb-0">
      <div className="mx-auto w-full max-w-7xl px-4 pt-10 sm:px-6">
        {/* The page ends on the latest close (stored data; drops out without it). */}
        <Suspense fallback={null}>
          <div className="mb-12">
            <FooterCloseLine />
          </div>
        </Suspense>
        <div className="grid gap-10 lg:grid-cols-[1fr_2.4fr]">
          <div className="max-w-xs">
            <Link href="/" className="inline-flex rounded-sm">
              <StockVizWordmark />
            </Link>
            <p className="mt-3 text-sm leading-6 text-text-secondary">
              A research and paper-trading workspace built on end-of-day market data.
            </p>
          </div>

          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {COLUMNS.map((column) => (
              <nav key={column.heading} aria-label={column.heading}>
                <h2 className="font-mono text-2xs font-semibold tracking-[0.02em] text-text-tertiary">
                  {titleCase(column.heading)}
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
              <span aria-hidden className="font-mono text-2xs text-brand tabular-nums">
                {index + 1}
              </span>
              <p className="text-2xs leading-5 text-text-tertiary">{note}</p>
            </li>
          ))}
        </ol>

        <div className="mt-10 flex flex-col gap-3 border-t border-border-muted pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-mono text-2xs text-text-tertiary">
            © {new Date().getFullYear()} StockViz · v{rootPackage.version}
          </p>
          <Suspense fallback={null}>
            <FooterStatus />
          </Suspense>
        </div>
      </div>

      {/* Closing graphic: the wordmark as display type filled with the hero's
          liquid metal (ChromeWordmark), clipped by the footer's own overflow
          so it reads as a watermark rather than a title. Decorative only —
          the real wordmark is the link above. On phones it is not cropped and
          the footer pads below it by the safe area: a phone browser's floating
          address bar covers the page's last strip, and a flush wordmark ended
          behind it. */}
      <ChromeWordmark className="mt-6 sm:-mb-[calc(0.18*clamp(4rem,17vw,15rem))]" />
    </footer>
  );
}
