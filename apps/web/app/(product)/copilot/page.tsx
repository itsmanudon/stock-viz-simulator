/**
 * /copilot — the AI Copilot workspace (A3.6), a placeholder until A8.
 *
 * Nothing here pretends to work: no input box, no sample answers. It says
 * what is planned and points at the workspaces that answer the same
 * questions today. Public, like the other research routes.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { PageFrame } from "@/components/page-frame";
import { MetaChip, PageEmptyState, PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "AI Copilot" };

const PLANNED = [
  "Answers grounded in the page you are on: the chart, the watchlist, the journal.",
  "Plain-English screens that turn into screener rules you can read and edit.",
  "A StockViz MCP server, so an agent can run a screen and a backtest.",
  "Every number in an answer links to the source it came from.",
] as const;

const TODAY = [
  { href: "/screener", label: "Screener", text: "write a screen as rules" },
  { href: "/checklist", label: "Checklist", text: "check a stock against six dimensions" },
  { href: "/backtest", label: "Backtest", text: "test a rule on stored history" },
] as const;

export default function CopilotPage() {
  return (
    <PageFrame>
      <PageHeader
        eyebrow="AI Copilot"
        title="Copilot"
        description="An assistant that reads what you are looking at. It is not built yet."
        meta={<MetaChip tone="warning">Planned for A8</MetaChip>}
      />
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <PageEmptyState title="Arrives in A8">
          <p>The AI layer is plan phase A8. What it is planned to do:</p>
          <ul className="mt-3 list-disc space-y-1.5 pl-5">
            {PLANNED.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </PageEmptyState>
        <section className="rounded-xl border border-border-muted bg-card px-4 py-6 sm:px-6">
          <h2 className="text-base font-semibold">Until Then</h2>
          <ul className="mt-3 space-y-2 text-sm text-text-secondary">
            {TODAY.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="font-medium text-foreground hover:underline">
                  {item.label}
                </Link>{" "}
                to {item.text}.
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-text-tertiary">
            Press <kbd className="rounded border px-1 font-mono text-3xs">⌘K</kbd> or{" "}
            <kbd className="rounded border px-1 font-mono text-3xs">Ctrl K</kbd> to jump to any
            symbol, page or action.
          </p>
        </section>
      </div>
    </PageFrame>
  );
}
