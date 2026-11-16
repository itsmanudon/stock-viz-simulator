import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { DOC_SECTIONS } from "@/lib/docs/nav";

export const metadata: Metadata = {
  title: "Docs",
  description:
    "How StockViz works: the paper account, orders, options and strategies, research, portfolio and risk, and how every figure is measured.",
};

export default function DocsOverview() {
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-[-0.025em] sm:text-4xl">StockViz docs</h1>
      <p className="mt-3 max-w-2xl text-lg leading-8 text-text-secondary text-pretty">
        StockViz is a paper-trading and research workspace on stored end-of-day prices. Nothing here
        is real money, and nothing is a live exchange quote. These pages explain what each part
        does, how to use it, and how its figures are worked out.
      </p>
      <div className="mt-10 space-y-10">
        {DOC_SECTIONS.map((section) => (
          <section key={section.title} aria-labelledby={`section-${section.title}`}>
            <h2 id={`section-${section.title}`} className="text-lg font-semibold">
              {section.title}
            </h2>
            <ul className="mt-3 grid gap-3 sm:grid-cols-2">
              {section.pages.map((page) => (
                <li key={page.slug}>
                  <Link
                    href={`/docs/${page.slug}`}
                    className="group flex h-full flex-col gap-2 rounded-2xl border border-border-muted bg-card p-5 transition-colors hover:border-border"
                  >
                    <span className="flex items-center justify-between gap-3 font-medium">
                      {page.title}
                      <ArrowRight
                        className="size-4 text-text-tertiary transition-transform group-hover:translate-x-0.5"
                        aria-hidden
                      />
                    </span>
                    <span className="text-sm leading-6 text-text-tertiary">{page.summary}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
