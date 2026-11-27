import Link from "next/link";

import { StockVizWordmark } from "@/components/brand/stockviz-mark";

import { AppNavigation, SimulatedDataTag } from "@/components/app-navigation";
import { homeHref } from "@/lib/app-navigation";

export function AppSidebar({
  signedIn,
  footer,
}: {
  signedIn: boolean;
  /** Optional block pinned under the navigation (the shell passes the market pulse). */
  footer?: React.ReactNode;
}) {
  return (
    <aside className="relative z-10 hidden h-screen w-60 flex-col border-r border-border-muted bg-surface-elevated/70 backdrop-blur-xl lg:sticky lg:top-0 lg:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-border-muted px-5">
        <Link
          href={homeHref(signedIn)}
          className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
        >
          <StockVizWordmark />
        </Link>
        <SimulatedDataTag />
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pt-3 pb-4">
        <AppNavigation signedIn={signedIn} />
      </div>
      {footer ? <div className="px-3 pb-3 empty:hidden">{footer}</div> : null}
    </aside>
  );
}
