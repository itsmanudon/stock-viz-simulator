/**
 * /charts — the chart workspace (A6.8, M2.10). Protected.
 *
 * One, two (side by side or stacked) or four charts, each with its own
 * symbol, interval and template, in linked colour groups: a pane in a colour
 * follows the last symbol chosen in that colour, and so does the watchlist
 * panel when it is in one. Panes showing the same symbol share the
 * crosshair time. The whole state is in the URL (`lib/chart-layouts.ts`);
 * `?layout=<id>` alone opens a saved layout. On phones the grid is tabs.
 */

import type { Metadata } from "next";

import { LayoutLibrary } from "@/components/chart-layouts/layout-library";
import { LayoutWorkspace } from "@/components/chart-layouts/layout-workspace";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import { getIndicatorCatalog } from "@/lib/api";
import {
  type ChartLayout,
  type ChartTemplate,
  getChartLayout,
  listChartLayouts,
  listChartTemplates,
} from "@/lib/api/chart-layouts";
import { AuthedApiError } from "@/lib/api/server";
import { type WatchlistItem, listWatchlist } from "@/lib/api/watchlist";
import {
  DEFAULT_SYMBOL,
  type WorkspaceQuery,
  type WorkspaceState,
  defaultPane,
  hasWorkspaceState,
  layoutState,
  parseWorkspace,
} from "@/lib/chart-layouts";
import { loadPaneView } from "@/lib/chart-layouts-server";

export const metadata: Metadata = { title: "Charts" };

export default async function ChartsPage({
  searchParams,
}: {
  searchParams: Promise<WorkspaceQuery>;
}) {
  const query = await searchParams;
  const requestedId = Number(query.layout);
  const layoutId = Number.isInteger(requestedId) && requestedId > 0 ? requestedId : null;

  const [layouts, templates, catalog, watchlist, opened] = await Promise.all([
    listChartLayouts().catch(() => null as ChartLayout[] | null),
    listChartTemplates().catch(() => null as ChartTemplate[] | null),
    getIndicatorCatalog().catch(() => null),
    listWatchlist().catch(() => null as WatchlistItem[] | null),
    layoutId
      ? getChartLayout(layoutId).catch((err) =>
          err instanceof AuthedApiError && err.status === 404 ? ("missing" as const) : null,
        )
      : Promise.resolve(null),
  ]);
  const savedLayout = opened && opened !== "missing" ? opened : null;

  // The URL's panes, else the saved layout's, else one chart on a watched
  // symbol (or the default).
  const state: WorkspaceState = hasWorkspaceState(query)
    ? parseWorkspace(query)
    : savedLayout
      ? { ...layoutState(savedLayout), watchlistLink: parseWorkspace(query).watchlistLink }
      : {
          grid: "1",
          panes: [defaultPane(watchlist?.[0]?.ticker ?? DEFAULT_SYMBOL)],
          watchlistLink: null,
        };
  const bounds = catalog ? Object.fromEntries(catalog.map((c) => [c.key, c.parameters])) : null;
  const views = await Promise.all(
    state.panes.map((pane) => loadPaneView(pane, templates ?? [], bounds)),
  );

  return (
    <PageFrame width="workstation" className="py-6 sm:py-8">
      <ResearchPageHeader
        path="/charts"
        title="Charts"
        description="Up to four charts at once, each with its own symbol, interval and template. Panes in one colour follow the same symbol; panes on the same symbol share the crosshair."
      />
      <ResearchSubnav current="/charts" />
      <div className="mt-6 grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_17rem] xl:items-start">
        <LayoutWorkspace
          state={state}
          views={views}
          layoutId={savedLayout?.id ?? null}
          layoutName={savedLayout?.name ?? null}
          layoutMissing={opened === "missing"}
          templates={(templates ?? []).map((t) => ({ id: t.id, name: t.name }))}
          watchlist={watchlist?.map((item) => ({ ticker: item.ticker, name: item.name })) ?? null}
        />
        <LayoutLibrary
          layouts={layouts}
          templates={templates}
          currentId={savedLayout?.id ?? null}
        />
      </div>
    </PageFrame>
  );
}
