import { LineChart } from "lucide-react";
import Link from "next/link";

import { AppNavigation } from "@/components/app-navigation";
import { homeHref } from "@/lib/app-navigation";

export function AppSidebar({ signedIn }: { signedIn: boolean }) {
  return (
    <aside className="hidden h-screen w-56 flex-col border-r border-border-muted bg-surface-elevated lg:sticky lg:top-0 lg:flex">
      <div className="flex h-13 items-center border-b border-border-muted px-4">
        <Link
          href={homeHref(signedIn)}
          className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-7 items-center justify-center rounded-sm border border-brand/40 bg-brand/10 text-brand">
            <LineChart className="size-4" aria-hidden />
          </span>
          <span>StockViz</span>
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-5">
        <AppNavigation signedIn={signedIn} />
      </div>
      <div className="border-t border-border-muted px-4 py-3 text-[11px] leading-relaxed text-text-tertiary">
        Research and simulation workspace
      </div>
    </aside>
  );
}
