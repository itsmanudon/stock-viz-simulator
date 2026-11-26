"use client";

/**
 * One pane of the chart workspace (A6.8): its controls (link colour, symbol,
 * interval, template) and the existing `PriceChart` with the template's
 * look. A pane whose symbol is unknown (a saved layout can outlive one) or
 * whose data failed says so and keeps its controls, so another symbol can be
 * chosen. Memoised: a crosshair move re-renders only the panes it reaches.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { memo, useCallback, useState } from "react";

import { LinkColourSelect } from "@/components/chart-layouts/link-colour";
import { PriceChart } from "@/components/price-chart";
import { Button } from "@/components/ui/button";
import {
  WORKSPACE_INTERVALS,
  type WorkspaceState,
  choosePaneInterval,
  choosePaneLink,
  choosePaneSymbol,
  choosePaneTemplate,
  cleanSymbol,
  linkLabel,
} from "@/lib/chart-layouts";
import type { PaneView } from "@/lib/chart-layouts-server";
import { chartTypeLabel } from "@/lib/chart-view";
import type { StockInterval } from "@/lib/stock-workspace";
import { listColourVar } from "@/lib/watchlist-columns";

const SELECT =
  "h-8 rounded-md border border-border-muted bg-card px-2 text-xs font-medium text-foreground hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60";

export const LayoutPane = memo(function LayoutPane({
  index,
  state,
  view,
  templates,
  go,
  onCrosshair,
  crosshairTime,
}: {
  index: number;
  state: WorkspaceState;
  view: PaneView;
  templates: { id: number; name: string }[];
  go: (next: WorkspaceState) => void;
  onCrosshair: (index: number, time: number | null) => void;
  crosshairTime: number | null | undefined;
}) {
  const pane = state.panes[index];
  const number = index + 1;
  const onTime = useCallback(
    (time: number | null) => onCrosshair(index, time),
    [onCrosshair, index],
  );
  const templateKnown = pane.templateId === null || templates.some((t) => t.id === pane.templateId);

  return (
    <section
      id={`chart-pane-${index}`}
      aria-label={`Chart ${number}: ${pane.symbol}`}
      className="min-w-0 overflow-hidden rounded-md border border-border-muted bg-card"
      style={
        pane.link ? { borderTopColor: listColourVar(pane.link), borderTopWidth: 3 } : undefined
      }
      data-testid={`chart-pane-${index}`}
      data-symbol={pane.symbol}
      data-interval={pane.interval}
      data-template={pane.templateId ?? ""}
      data-link={pane.link ?? ""}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border-muted px-2 py-2">
        <LinkColourSelect
          label={`Link colour for chart ${number}`}
          value={pane.link}
          onChange={(link) => go(choosePaneLink(state, index, link))}
          testId={`pane-link-${index}`}
        />
        <SymbolForm
          key={pane.symbol}
          number={number}
          symbol={pane.symbol}
          onChoose={(symbol) => go(choosePaneSymbol(state, index, symbol))}
          testId={`pane-symbol-${index}`}
        />
        <select
          aria-label={`Interval for chart ${number}`}
          value={pane.interval}
          onChange={(event) =>
            go(choosePaneInterval(state, index, event.target.value as StockInterval))
          }
          className={SELECT}
          data-testid={`pane-interval-${index}`}
        >
          {WORKSPACE_INTERVALS.map((interval) => (
            <option key={interval.value} value={interval.value}>
              {interval.label}
            </option>
          ))}
        </select>
        <select
          aria-label={`Template for chart ${number}`}
          value={templateKnown ? (pane.templateId ?? "") : ""}
          onChange={(event) =>
            go(
              choosePaneTemplate(
                state,
                index,
                event.target.value ? Number(event.target.value) : null,
              ),
            )
          }
          className={SELECT}
          data-testid={`pane-template-${index}`}
        >
          <option value="">Default look</option>
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
        <Link
          href={`/stocks/${encodeURIComponent(pane.symbol)}`}
          className="ml-auto text-xs text-text-secondary underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        >
          Open <span className="ticker">{pane.symbol}</span>
        </Link>
      </div>
      <PaneBody
        view={view}
        pane={pane}
        number={number}
        templateKnown={templateKnown}
        crosshairTime={crosshairTime}
        onTime={onTime}
      />
    </section>
  );
});

function PaneBody({
  view,
  pane,
  number,
  templateKnown,
  crosshairTime,
  onTime,
}: {
  view: PaneView;
  pane: WorkspaceState["panes"][number];
  number: number;
  templateKnown: boolean;
  crosshairTime: number | null | undefined;
  onTime: (time: number | null) => void;
}) {
  const router = useRouter();
  if (view.status === "missing") {
    return (
      <div
        className="px-4 py-16 text-center text-sm text-text-secondary"
        data-testid="pane-missing"
      >
        <p>
          <span className="ticker font-semibold">{view.symbol}</span> is not a symbol StockViz has.
        </p>
        <p className="mt-1 text-xs text-text-tertiary">
          Choose another symbol for chart {number} above.
        </p>
      </div>
    );
  }
  if (view.status === "error") {
    return (
      <div className="px-4 py-16 text-center text-sm text-text-secondary" data-testid="pane-error">
        <p>
          The chart for <span className="ticker font-semibold">{view.symbol}</span> could not load.
        </p>
        <Button className="mt-3" size="sm" variant="outline" onClick={() => router.refresh()}>
          Try again
        </Button>
      </div>
    );
  }
  const look = [
    view.templateName ?? "Default look",
    chartTypeLabel(view.chartType),
    view.scale === "linear" ? null : view.scale === "log" ? "Log scale" : "Percent scale",
    pane.link ? `Linked: ${linkLabel(pane.link)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="p-1.5 sm:p-2">
      <p className="px-1 pb-1 text-2xs text-text-tertiary" data-testid="pane-look">
        {view.name} · {look}
        {templateKnown ? "" : " · its template was deleted"}
      </p>
      {view.note ? (
        <p className="px-1 pb-1 text-2xs text-text-secondary" data-testid="pane-note">
          {view.note}
        </p>
      ) : null}
      {view.bars.length ? (
        <PriceChart
          // The template's pane heights are read when the chart mounts.
          key={`${view.symbol}|${view.interval}|${pane.templateId ?? ""}`}
          bars={view.bars}
          overlays={view.overlays}
          panes={view.panes}
          rsi={view.rsi}
          macd={view.macd}
          rsiKey={view.rsiKey}
          macdKey={view.macdKey}
          interval={view.interval}
          chartType={view.chartType}
          scale={view.scale}
          paneHeights={view.paneHeights ?? undefined}
          timeZone={view.timeZone}
          sourceFeed={view.sourceFeed}
          crosshairTime={crosshairTime}
          onCrosshairTime={onTime}
        />
      ) : (
        <p className="py-16 text-center text-sm text-text-secondary" data-testid="pane-empty">
          No bars for <span className="ticker">{view.symbol}</span> at this interval.
        </p>
      )}
    </div>
  );
}

function SymbolForm({
  number,
  symbol,
  onChoose,
  testId,
}: {
  number: number;
  symbol: string;
  onChoose: (symbol: string) => void;
  testId: string;
}) {
  const [value, setValue] = useState(symbol);
  const [error, setError] = useState<string | null>(null);
  const errorId = `${testId}-error`;
  return (
    <form
      className="inline-flex items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        const cleaned = cleanSymbol(value);
        if (!cleaned) {
          setError("Type a symbol, such as AAPL.");
          return;
        }
        setError(null);
        if (cleaned !== symbol) onChoose(cleaned);
      }}
    >
      <input
        aria-label={`Symbol for chart ${number}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        maxLength={32}
        autoCapitalize="characters"
        spellCheck={false}
        className="ticker h-8 w-24 rounded-md border border-input bg-card px-2 text-xs font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        data-testid={testId}
      />
      <Button type="submit" size="sm" variant="outline" className="h-8">
        Go
      </Button>
      {error ? (
        <span id={errorId} role="alert" className="text-2xs text-negative">
          {error}
        </span>
      ) : null}
    </form>
  );
}
