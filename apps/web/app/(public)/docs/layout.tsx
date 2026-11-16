import type { ReactNode } from "react";

import { DocsNav } from "@/components/docs/docs-nav";

/**
 * /docs: the public user guide. A sidebar of sections beside the page; on
 * small screens the contents sit above it. Public on purpose: it explains
 * features and holds no user data (owner, 16 Nov 2026).
 */
export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 pt-10 pb-20 sm:px-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-12 lg:pt-16">
      <aside>
        <DocsNav />
      </aside>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
