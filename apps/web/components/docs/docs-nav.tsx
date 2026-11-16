"use client";

/**
 * The /docs sidebar: every section and page, the current one marked. On
 * small screens it collapses behind a "Contents" disclosure above the page.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DOC_SECTIONS } from "@/lib/docs/nav";
import { cn } from "@/lib/utils";

function Links() {
  const path = usePathname();
  return (
    <div className="space-y-6">
      <Link
        href="/docs"
        aria-current={path === "/docs" ? "page" : undefined}
        className={cn(
          "block text-sm font-medium",
          path === "/docs" ? "text-brand" : "text-foreground hover:text-brand",
        )}
      >
        Overview
      </Link>
      {DOC_SECTIONS.map((section) => (
        <div key={section.title}>
          <p className="text-2xs font-medium uppercase tracking-wider text-text-tertiary">
            {section.title}
          </p>
          <ul className="mt-2 space-y-1.5">
            {section.pages.map((page) => {
              const href = `/docs/${page.slug}`;
              const current = path === href;
              return (
                <li key={page.slug}>
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "block text-sm",
                      current ? "text-brand" : "text-text-secondary hover:text-foreground",
                    )}
                  >
                    {page.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function DocsNav() {
  return (
    <>
      <details className="rounded-xl border border-border-muted px-4 py-3 lg:hidden">
        <summary className="cursor-pointer text-sm font-medium">Contents</summary>
        <nav aria-label="Documentation" className="mt-4">
          <Links />
        </nav>
      </details>
      <nav aria-label="Documentation" className="sticky top-24 hidden lg:block">
        <Links />
      </nav>
    </>
  );
}
