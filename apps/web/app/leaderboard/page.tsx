/**
 * /leaderboard — top 50 users ranked by portfolio return %.
 *
 * Public page (no auth required). Data is cached server-side for 1 hour by
 * the FastAPI leaderboard endpoint. Users must opt in via /settings to appear.
 */

import Link from "next/link";

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
    <div className="container mx-auto px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Leaderboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Top 50 traders by portfolio return. Opt in from{" "}
          <Link href="/settings" className="text-foreground underline">
            Settings
          </Link>
          .
        </p>
      </header>

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
        <div className="rounded-lg border">
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
              {entries.map((e) => {
                const positive = e.return_pct >= 0;
                return (
                  <TableRow key={e.user_id}>
                    <TableCell className="text-center font-mono text-muted-foreground">
                      {e.rank === 1 ? "🥇" : e.rank === 2 ? "🥈" : e.rank === 3 ? "🥉" : e.rank}
                    </TableCell>
                    <TableCell className="font-medium">{e.username}</TableCell>
                    <TableCell
                      className={`text-right font-mono ${positive ? "text-green-500" : "text-red-500"}`}
                    >
                      {fmtPct(e.return_pct)}
                    </TableCell>
                    <TableCell className="hidden text-right font-mono sm:table-cell">
                      {fmtCurrency(e.portfolio_value)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
