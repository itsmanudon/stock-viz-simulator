"use client";

import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ReplayEpisodeForensics, ReplayForensics } from "@/lib/api/replay";
import {
  formatCurrency,
  formatQuantity,
  formatSignedCurrency,
  formatSignedPercent,
} from "@/lib/portfolio-view-model";
import { formatReplayShortDate } from "@/lib/replay";
import { cn } from "@/lib/utils";

function pct(raw: string | null | undefined): string {
  if (raw == null) return "—";
  return formatSignedPercent(Number(raw));
}

function signedClass(raw: string | null | undefined): string {
  if (raw == null) return "";
  const value = Number(raw);
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "";
}

function scopeLabel(scope: ReplayForensics["analysis_scope"]): string {
  if (scope === "so_far") return "So far";
  if (scope === "cancelled") return "Cancelled";
  return "Final analysis";
}

export function ReplayForensicsPanel({
  forensics,
}: {
  forensics: ReplayForensics;
}) {
  return (
    <div className="space-y-8">
      <ReplayScorecard forensics={forensics} />
      <ReplayEpisodeTable episodes={forensics.episodes} />
    </div>
  );
}

function sessionExcursion(
  episodes: ReplayEpisodeForensics[],
  field: "mae_pct" | "mfe_pct",
  pick: "min" | "max",
): string | null {
  const values = episodes
    .map((episode) => episode[field])
    .filter((value): value is string => value != null);
  if (values.length === 0) return null;
  return values.reduce((best, value) => {
    const left = Number(best);
    const right = Number(value);
    if (pick === "min") return right < left ? value : best;
    return right > left ? value : best;
  });
}

export function ReplayScorecard({ forensics }: { forensics: ReplayForensics }) {
  const mae = sessionExcursion(forensics.episodes, "mae_pct", "min");
  const mfe = sessionExcursion(forensics.episodes, "mfe_pct", "max");
  const items = [
    ["Replay return", pct(forensics.replay_return_pct), forensics.replay_return_pct],
    ["Buy & hold", pct(forensics.buy_hold_return_pct), forensics.buy_hold_return_pct],
    ["Excess return", pct(forensics.excess_return_pct), forensics.excess_return_pct],
    ["Max adverse excursion", pct(mae), mae],
    ["Max favorable excursion", pct(mfe), mfe],
    [
      "Peak concentration",
      forensics.max_concentration_pct == null
        ? "—"
        : `${Number(forensics.max_concentration_pct).toFixed(2)}%`,
      null,
    ],
    ["Episodes", String(forensics.episodes_count), null],
    ["Fills", String(forensics.fills_count), null],
  ] as const;

  return (
    <section aria-labelledby="replay-forensics-scorecard" className="space-y-3">
      <p className="text-sm font-medium text-foreground">{scopeLabel(forensics.analysis_scope)}</p>
      <ResearchSectionHeader
        id="replay-forensics-scorecard"
        title="Trade forensics"
        description="Percent comparison versus same-symbol buy-and-hold over stored daily bars through the replay clock. MAE/MFE use observed daily high/low after each bar, not execution timestamps."
      />
      <dl className="grid grid-cols-2 gap-3 border-y border-border-muted py-4 text-sm sm:grid-cols-3 lg:grid-cols-4 sm:border-x sm:px-6">
        {items.map(([label, value, signed]) => (
          <div key={label}>
            <dt className="text-xs text-text-tertiary">{label}</dt>
            <dd className={cn("font-mono tabular-nums", signedClass(signed))}>{value}</dd>
          </div>
        ))}
      </dl>
      {forensics.max_drawdown_pct != null ? (
        <p className="text-xs text-text-tertiary">
          Replay equity max drawdown {pct(forensics.max_drawdown_pct)} (marked at stored closes;
          fills use actual fill prices).
        </p>
      ) : null}
    </section>
  );
}

function ReplayEpisodeTable({ episodes }: { episodes: ReplayEpisodeForensics[] }) {
  if (episodes.length === 0) {
    return (
      <ResearchEmptyState title="No trade episodes yet.">
        Forensics reconstructs opening exposure through a full exit. Partial sells stay in one
        episode. Analysis uses only bars visible at the replay date.
      </ResearchEmptyState>
    );
  }

  return (
    <section aria-labelledby="replay-episodes-heading" className="space-y-3">
      <ResearchSectionHeader
        id="replay-episodes-heading"
        title="Episodes"
        description="One row per completed or open exposure. Expand for fills, sizing, and execution provenance."
      />
      <div className="overflow-x-auto border-y border-border-muted sm:border-x">
        <Table aria-label="Replay episodes">
          <TableHeader>
            <TableRow>
              <TableHead>Entry</TableHead>
              <TableHead>Exit</TableHead>
              <TableHead className="text-right">Return</TableHead>
              <TableHead className="text-right">MAE</TableHead>
              <TableHead className="text-right">MFE</TableHead>
              <TableHead className="text-right">Benchmark</TableHead>
              <TableHead className="text-right">Excess</TableHead>
              <TableHead className="text-right">Bars held</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {episodes.map((episode) => (
              <ReplayEpisodeRows key={episode.index} episode={episode} />
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function ReplayEpisodeRows({ episode }: { episode: ReplayEpisodeForensics }) {
  return (
    <>
      <TableRow>
        <TableCell>
          <div>{formatReplayShortDate(episode.opened_at)}</div>
          <div className="font-mono text-xs tabular-nums text-text-tertiary">
            {formatCurrency(episode.entry_price)}
            {episode.status === "open" ? " · open" : ""}
          </div>
        </TableCell>
        <TableCell>
          {episode.closed_at && episode.exit_price ? (
            <>
              <div>{formatReplayShortDate(episode.closed_at)}</div>
              <div className="font-mono text-xs tabular-nums text-text-tertiary">
                {formatCurrency(episode.exit_price)}
              </div>
            </>
          ) : (
            "—"
          )}
        </TableCell>
        <TableCell
          className={cn("text-right font-mono tabular-nums", signedClass(episode.return_pct))}
        >
          {pct(episode.return_pct)}
        </TableCell>
        <TableCell
          className={cn("text-right font-mono tabular-nums", signedClass(episode.mae_pct))}
        >
          {pct(episode.mae_pct)}
        </TableCell>
        <TableCell
          className={cn("text-right font-mono tabular-nums", signedClass(episode.mfe_pct))}
        >
          {pct(episode.mfe_pct)}
        </TableCell>
        <TableCell
          className={cn(
            "text-right font-mono tabular-nums",
            signedClass(episode.benchmark_return_pct),
          )}
        >
          {pct(episode.benchmark_return_pct)}
        </TableCell>
        <TableCell
          className={cn(
            "text-right font-mono tabular-nums",
            signedClass(episode.excess_return_pct),
          )}
        >
          {pct(episode.excess_return_pct)}
        </TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {episode.holding_bars}
          <div className="text-xs text-text-tertiary">{episode.holding_calendar_days} calendar</div>
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={8} className="bg-surface-elevated/40">
          <details>
            <summary className="cursor-pointer text-xs font-medium text-text-secondary">
              Episode {episode.index} detail
            </summary>
            <dl className="mt-3 grid gap-2 text-xs text-text-tertiary sm:grid-cols-2 lg:grid-cols-4">
              <div>Weighted entry {formatCurrency(episode.weighted_entry_price)}</div>
              <div>
                Weighted exit{" "}
                {episode.weighted_exit_price ? formatCurrency(episode.weighted_exit_price) : "—"}
              </div>
              <div>Peak quantity {formatQuantity(episode.peak_quantity)}</div>
              <div>Peak exposure {formatCurrency(episode.peak_exposure)}</div>
              <div>Realized P&amp;L {formatSignedCurrency(episode.realized_pnl)}</div>
              <div>
                Unrealized{" "}
                {episode.unrealized_pnl == null
                  ? "—"
                  : formatSignedCurrency(episode.unrealized_pnl)}
              </div>
              <div>
                Position exposure{" "}
                {episode.max_position_pct == null
                  ? "—"
                  : `${Number(episode.max_position_pct).toFixed(2)}% of replay equity`}
              </div>
              <div>Replay concentration only — not multi-asset diversification.</div>
            </dl>
            <p className="mt-3 text-xs text-text-tertiary">
              MAE {pct(episode.mae_pct)} is the worst daily low versus the active weighted entry
              while the position was open. MFE {pct(episode.mfe_pct)} is the best daily high. Daily
              high/low is retrospective range, not an execution time.
            </p>
            <ul className="mt-3 space-y-2">
              {episode.fills.map((fill) => (
                <li key={fill.id} className="border-t border-border-muted pt-2 text-xs">
                  <p className="text-text-secondary">
                    {formatReplayShortDate(fill.evaluated_at)} {fill.side.toUpperCase()}{" "}
                    {formatQuantity(fill.quantity)} @ {formatCurrency(fill.fill_price)}
                  </p>
                  <p className="text-text-tertiary">
                    {fill.profile_name} {fill.model_version} · {fill.reason}
                    {fill.concentration_pct != null
                      ? ` · exposure ${Number(fill.concentration_pct).toFixed(2)}%`
                      : ""}
                  </p>
                  {fill.assumptions.length > 0 ? (
                    <ul className="mt-1 list-disc pl-4 text-text-tertiary">
                      {fill.assumptions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        </TableCell>
      </TableRow>
    </>
  );
}
