"use client";

/**
 * The chart workspace (A6.8, M2.10): the grid of panes, its toolbar (grid,
 * save), the phone tabs and the linked watchlist.
 *
 * Every change is a new URL (`lib/chart-layouts.ts`), so the server reads
 * the panes again and the state can be shared and reloaded. The crosshair is
 * the one piece of state kept here: the pane under the pointer hands its time
 * to the other panes on the same symbol (`syncedBarIndex` places it at each
 * pane's interval).
 */

import { useRouter } from "next/navigation";
import { type KeyboardEvent, useCallback, useRef, useState, useTransition } from "react";

import { saveLayoutAction } from "@/app/(product)/(authed)/charts/actions";
import { LayoutPane } from "@/components/chart-layouts/layout-pane";
import { LinkColourSelect, LinkDot } from "@/components/chart-layouts/link-colour";
import { Button } from "@/components/ui/button";
import {
  CHART_GRIDS,
  type ChartGrid,
  type LinkColour,
  type WorkspaceState,
  chooseColourSymbol,
  chooseGrid,
  chooseWatchlistLink,
  colourSymbol,
  layoutBody,
  workspaceHref,
} from "@/lib/chart-layouts";
import type { PaneView } from "@/lib/chart-layouts-server";
import { cn } from "@/lib/utils";

const GRID_CLASS: Record<ChartGrid, string> = {
  "1": "grid-cols-1",
  "2v": "grid-cols-1 md:grid-cols-2",
  "2h": "grid-cols-1",
  "4": "grid-cols-1 md:grid-cols-2",
};

type Sync = { source: number; symbol: string; time: number | null };

export function LayoutWorkspace({
  state,
  views,
  layoutId,
  layoutName,
  layoutMissing,
  templates,
  watchlist,
}: {
  state: WorkspaceState;
  views: PaneView[];
  layoutId: number | null;
  layoutName: string | null;
  layoutMissing: boolean;
  templates: { id: number; name: string }[];
  watchlist: { ticker: string; name: string }[] | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [active, setActive] = useState(0);
  const [sync, setSync] = useState<Sync | null>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const go = useCallback(
    (next: WorkspaceState) => {
      startTransition(() => router.push(workspaceHref(next, layoutId)));
    },
    [router, layoutId],
  );

  const onCrosshair = useCallback(
    (index: number, time: number | null) => {
      const symbol = state.panes[index]?.symbol;
      if (!symbol) return;
      setSync((prev) =>
        time === null && (prev === null || prev.source !== index)
          ? prev
          : { source: index, symbol, time },
      );
    },
    [state.panes],
  );

  const tab = Math.min(active, state.panes.length - 1);
  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const count = state.panes.length;
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (tab + 1) % count;
    else if (event.key === "ArrowLeft") next = (tab - 1 + count) % count;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    if (next === null) return;
    event.preventDefault();
    setActive(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <section aria-label="Chart workspace" aria-busy={pending} className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end gap-3 rounded-md border border-border-muted bg-card p-3">
        <label className="grid gap-1 text-xs font-medium text-text-secondary">
          Grid
          <select
            value={state.grid}
            onChange={(event) => go(chooseGrid(state, event.target.value as ChartGrid))}
            className="h-8 rounded-md border border-border-muted bg-card px-2 text-xs font-medium text-foreground hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
            data-testid="layout-grid"
          >
            {CHART_GRIDS.map((grid) => (
              <option key={grid.value} value={grid.value}>
                {grid.label}
              </option>
            ))}
          </select>
        </label>
        <SaveLayoutForm
          key={layoutId ?? "new"}
          state={state}
          layoutId={layoutId}
          layoutName={layoutName}
        />
        <output aria-live="polite" className="text-xs text-text-tertiary">
          {pending ? "Loading charts…" : ""}
        </output>
      </div>
      {layoutMissing ? (
        <p className="rounded-md border border-border-muted px-3 py-2 text-xs text-text-secondary">
          That saved layout no longer exists; this is a new workspace.
        </p>
      ) : null}

      {state.panes.length > 1 ? (
        <div
          role="tablist"
          aria-label="Charts"
          className="flex gap-1 overflow-x-auto md:hidden"
          onKeyDown={onTabKey}
          data-testid="layout-tabs"
        >
          {state.panes.map((pane, n) => (
            <button
              // biome-ignore lint/suspicious/noArrayIndexKey: panes are positional.
              key={n}
              ref={(el) => {
                tabRefs.current[n] = el;
              }}
              type="button"
              role="tab"
              id={`chart-tab-${n}`}
              aria-selected={n === tab}
              aria-controls={`chart-pane-${n}`}
              tabIndex={n === tab ? 0 : -1}
              onClick={() => setActive(n)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60",
                n === tab
                  ? "border-foreground bg-surface-elevated text-foreground"
                  : "border-border-muted text-text-secondary",
              )}
            >
              {pane.link ? <LinkDot colour={pane.link} /> : null}
              <span className="ticker">{pane.symbol}</span>
              <span className="text-text-tertiary">{n + 1}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className={cn("grid min-w-0 gap-3", GRID_CLASS[state.grid])} data-grid={state.grid}>
        {state.panes.map((pane, n) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: panes are positional.
            key={n}
            className={cn("min-w-0", n !== tab && "max-md:hidden")}
          >
            <LayoutPane
              index={n}
              state={state}
              view={views[n]}
              templates={templates}
              go={go}
              onCrosshair={onCrosshair}
              crosshairTime={
                sync === null || sync.source === n
                  ? undefined
                  : sync.symbol === pane.symbol
                    ? sync.time
                    : null
              }
            />
          </div>
        ))}
      </div>

      {watchlist ? <LinkedWatchlist state={state} watchlist={watchlist} go={go} /> : null}
    </section>
  );
}

function SaveLayoutForm({
  state,
  layoutId,
  layoutName,
}: {
  state: WorkspaceState;
  layoutId: number | null;
  layoutName: string | null;
}) {
  const router = useRouter();
  const [name, setName] = useState(layoutName ?? "");
  const [saving, startSaving] = useTransition();
  const [message, setMessage] = useState<{ error?: string; ok?: string } | null>(null);

  const save = (asNew: boolean) => {
    const cleaned = name.trim();
    if (!cleaned) {
      setMessage({ error: "Name the layout first." });
      return;
    }
    startSaving(async () => {
      const result = await saveLayoutAction(asNew ? null : layoutId, {
        name: cleaned,
        ...layoutBody(state),
      });
      if (result.error || !result.id) {
        setMessage({ error: result.error ?? "The layout could not be saved." });
        return;
      }
      setMessage({ ok: `Saved ${cleaned}.` });
      router.push(workspaceHref(state, result.id));
    });
  };

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        save(false);
      }}
    >
      <label className="grid gap-1 text-xs font-medium text-text-secondary">
        Layout name
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={64}
          className="h-8 w-44 rounded-md border border-input bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
          data-testid="layout-name"
        />
      </label>
      <Button type="submit" size="sm" disabled={saving} data-testid="layout-save">
        {layoutId ? "Save changes" : "Save layout"}
      </Button>
      {layoutId ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={saving}
          onClick={() => save(true)}
        >
          Save as new
        </Button>
      ) : null}
      {message?.error ? (
        <p role="alert" className="text-xs text-negative">
          {message.error}
        </p>
      ) : message?.ok ? (
        <p className="text-xs text-text-secondary" data-testid="layout-saved">
          {message.ok}
        </p>
      ) : null}
    </form>
  );
}

/**
 * The default watchlist as a linked widget: in a colour, a click sends the
 * symbol to every pane in that colour, and the colour's current symbol is
 * marked. Unlinked, the rows open the stock page.
 */
function LinkedWatchlist({
  state,
  watchlist,
  go,
}: {
  state: WorkspaceState;
  watchlist: { ticker: string; name: string }[];
  go: (next: WorkspaceState) => void;
}) {
  const link = state.watchlistLink;
  const current = link ? colourSymbol(state, link) : null;
  return (
    <section
      aria-labelledby="layout-watchlist-title"
      className="rounded-md border border-border-muted bg-card p-3"
      data-testid="layout-watchlist"
      data-link={link ?? ""}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="layout-watchlist-title" className="text-sm font-semibold tracking-tight">
          Watchlist
        </h2>
        <LinkColourSelect
          label="Watchlist link colour"
          value={link}
          onChange={(next: LinkColour | null) => go(chooseWatchlistLink(state, next))}
        />
      </div>
      {watchlist.length === 0 ? (
        <p className="text-xs text-text-tertiary">Your default watchlist is empty.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {watchlist.map((item) => (
            <li key={item.ticker}>
              {link ? (
                <button
                  type="button"
                  title={item.name}
                  aria-pressed={item.ticker === current}
                  onClick={() => go(chooseColourSymbol(state, link, item.ticker))}
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60",
                    item.ticker === current
                      ? "border-foreground bg-surface-elevated text-foreground"
                      : "border-border-muted text-text-secondary hover:bg-surface-hover",
                  )}
                >
                  <span className="ticker">{item.ticker}</span>
                </button>
              ) : (
                <a
                  href={`/stocks/${encodeURIComponent(item.ticker)}`}
                  title={item.name}
                  className="inline-block rounded-md border border-border-muted px-2 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
                >
                  <span className="ticker">{item.ticker}</span>
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-2xs text-text-tertiary">
        {link
          ? `Linked in ${link}: a symbol here moves every ${link} chart.`
          : "Unlinked: pick a colour to drive the charts in it from this list."}
      </p>
    </section>
  );
}
