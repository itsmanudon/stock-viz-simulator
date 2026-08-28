/**
 * /leaderboard — top 50 users ranked by portfolio return %.
 *
 * Public page (no auth required). Data is cached server-side for 1 hour by
 * the FastAPI leaderboard endpoint. Users must opt in via /settings to appear.
 */

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
import { getLeaderboard } from "@/lib/api/leaderboard";

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
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <PageHeader
        eyebrow="Community"
        title="Leaderboard"
        description="Top 50 traders by portfolio return, across every public paper portfolio."
        meta={
          <>
            Opt in from{" "}
            <Link href="/settings" className="text-foreground underline">
              Settings
            </Link>
            .
          </>
        }
      />

      <div className="mt-6">
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
          <DataTableFrame>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14 text-center">Rank</TableHead>
                  <TableHead>Trader</TableHead>
                  <TableHead className="text-right">Return</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Portfolio value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((e) => (
                  <TableRow key={e.user_id}>
                    <TableCell className="text-center font-mono text-text-tertiary">
                      {e.rank === 1 ? "🥇" : e.rank === 2 ? "🥈" : e.rank === 3 ? "🥉" : e.rank}
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
        )}
      </div>
    </div>
  );
}
