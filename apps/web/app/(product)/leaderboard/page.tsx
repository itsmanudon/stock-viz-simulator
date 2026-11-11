/**
 * /leaderboard — top 50 users ranked by portfolio return %.
 *
 * Public page (no auth required). Fetched fresh on every request
 * (`getLeaderboard` uses `cache: "no-store"`), so an opt-out in /settings
 * takes effect at once. Users must opt in via /settings to appear.
 *
 * Aurora: the top three stand on a podium above the full table, with the one
 * brand glow behind first place. Ranks are numbers in chips, not emoji.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { DataTableFrame, NumericCell } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";

import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type LeaderboardEntry, getLeaderboard } from "@/lib/api/leaderboard";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Leaderboard" };

function fmtCurrency(raw: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export default async function LeaderboardPage() {
  const entries = await getLeaderboard().catch(() => []);

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Community"
        title="Leaderboard"
        description="Public paper traders ranked by portfolio return. Only opted-in profiles appear."
        meta={
          <>
            {entries.length} public trader{entries.length === 1 ? "" : "s"} · opt in from{" "}
            <Link href="/settings" className="text-foreground underline">
              Settings
            </Link>
            .
          </>
        }
      />

      <div className="mt-5">
        {entries.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No public profiles yet. Be the first to{" "}
              <Link href="/settings" className="text-foreground underline">
                opt in
              </Link>
              .
            </CardContent>
          </Card>
        ) : (
          <>
            {entries.length >= 3 ? <Podium top={entries.slice(0, 3)} /> : null}
            <DataTableFrame>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-14 text-center">Rank</TableHead>
                    <TableHead>Trader</TableHead>
                    <TableHead className="text-right">Return</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">
                      Portfolio value · USD
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((e) => (
                    <TableRow key={e.user_id}>
                      <TableCell className="text-center">
                        <RankChip rank={e.rank} />
                      </TableCell>
                      <TableCell className="font-medium">{e.username}</TableCell>
                      <NumericCell signedBy={e.return_pct}>{fmtPct(e.return_pct)}</NumericCell>
                      <NumericCell className="hidden sm:table-cell">
                        {fmtCurrency(e.portfolio_value)}
                      </NumericCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </DataTableFrame>
          </>
        )}
      </div>
    </div>
  );
}

function RankChip({ rank }: { rank: number }) {
  return (
    <span
      className={cn(
        "inline-grid size-7 place-items-center rounded-full font-mono text-xs",
        rank === 1
          ? "bg-primary text-primary-foreground"
          : rank <= 3
            ? "border border-border text-foreground"
            : "text-text-tertiary",
      )}
    >
      {rank}
    </span>
  );
}

/** First place in the middle and raised, second on the left, third on the right. */
function Podium({ top }: { top: LeaderboardEntry[] }) {
  const order = [top[1], top[0], top[2]];
  return (
    <ol
      aria-label="Top three traders"
      className="mb-5 grid grid-cols-3 items-end gap-3 rounded-2xl border border-border-muted bg-card p-3 sm:p-4"
    >
      {order.map((entry) => {
        const first = entry.rank === 1;
        const up = entry.return_pct >= 0;
        return (
          <li
            key={entry.user_id}
            className={cn(
              "relative isolate grid justify-items-center gap-1.5 overflow-hidden rounded-xl border border-border-muted bg-surface-secondary/60 px-3 text-center",
              first ? "pt-7 pb-6" : "pt-5 pb-4",
            )}
          >
            {first ? (
              <div aria-hidden className="brand-glow -bottom-16 -z-10 h-32 w-48 opacity-70" />
            ) : null}
            <RankChip rank={entry.rank} />
            <span className="max-w-full truncate text-sm font-medium">{entry.username}</span>
            <span
              className={cn(
                "font-mono",
                first ? "text-2xl" : "text-lg",
                up ? "text-positive" : "text-negative",
              )}
              data-financial
            >
              {up ? "▲ " : "▼ "}
              {fmtPct(entry.return_pct)}
            </span>
            <span className="font-mono text-2xs text-text-tertiary tabular-nums" data-financial>
              {fmtCurrency(entry.portfolio_value)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
