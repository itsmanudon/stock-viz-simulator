import { LineChart } from "lucide-react";
import Link from "next/link";

import { AppNavigation } from "@/components/app-navigation";

export function AppSidebar() {
  return (
    <aside className="hidden h-screen w-56 flex-col border-r bg-card lg:sticky lg:top-0 lg:flex">
      <div className="flex h-13 items-center border-b px-4">
        <Link
          href="/dashboard"
          className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-7 items-center justify-center rounded-sm border border-primary/30 bg-primary/10 text-primary">
            <LineChart className="size-4" aria-hidden />
          </span>
          <span>StockViz</span>
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-5">
        <AppNavigation />
      </div>
      <div className="border-t px-4 py-3 text-[11px] leading-relaxed text-muted-foreground">
        Research and simulation workspace
      </div>
    </aside>
  );
}
