import { LineChart } from "lucide-react";
import Link from "next/link";

import { AppNavigation, SimulatedDataTag } from "@/components/app-navigation";
import { homeHref } from "@/lib/app-navigation";

export function AppSidebar({ signedIn }: { signedIn: boolean }) {
  return (
    <aside className="hidden h-screen w-60 flex-col border-r border-border-muted bg-surface-elevated lg:sticky lg:top-0 lg:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-border-muted px-5">
        <Link
          href={homeHref(signedIn)}
          className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-7 items-center justify-center rounded-md border border-brand/40 bg-brand/10 text-brand">
            <LineChart className="size-4" aria-hidden />
          </span>
          <span>StockViz</span>
        </Link>
        <SimulatedDataTag />
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pt-3 pb-4">
        <AppNavigation signedIn={signedIn} />
      </div>
    </aside>
  );
}
