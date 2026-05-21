/**
 * Open options positions block for /portfolio.
 *
 * Server component — the per-row "Close" button posts to the closeOptionAction
 * server action, which sells the contract back at its theoretical value.
 */

import { closeOptionAction } from "@/app/(authed)/trade/options-actions";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { OptionPosition } from "@/lib/api/options";

function fmtCurrency(raw: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

export function OptionsPositions({ positions }: { positions: OptionPosition[] }) {
  if (positions.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          No open options positions. Buy a call or put from the trade page.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[90px]">Ticker</TableHead>
            <TableHead className="w-[64px]">Type</TableHead>
            <TableHead className="text-right">Strike</TableHead>
            <TableHead className="hidden text-right sm:table-cell">Contracts</TableHead>
            <TableHead className="hidden md:table-cell">Expiry</TableHead>
            <TableHead className="hidden text-right md:table-cell">Premium paid</TableHead>
            <TableHead className="text-right">Value now</TableHead>
            <TableHead className="text-right">P&amp;L</TableHead>
            <TableHead className="w-[80px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p) => {
            const pl = Number(p.current_value) - Number(p.premium_paid);
            return (
              <TableRow key={p.id}>
                <TableCell className="font-mono font-semibold">{p.ticker}</TableCell>
                <TableCell
                  className={`font-medium uppercase ${
                    p.option_type === "call" ? "text-green-500" : "text-red-500"
                  }`}
                >
                  {p.option_type}
                </TableCell>
                <TableCell className="text-right font-mono">{fmtCurrency(p.strike)}</TableCell>
                <TableCell className="hidden text-right font-mono sm:table-cell">
                  {p.quantity}
                </TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {p.expiry}
                </TableCell>
                <TableCell className="hidden text-right font-mono md:table-cell">
                  {fmtCurrency(p.premium_paid)}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {fmtCurrency(p.current_value)}
                </TableCell>
                <TableCell
                  className={`text-right font-mono ${
                    pl > 0 ? "text-green-500" : pl < 0 ? "text-red-500" : ""
                  }`}
                >
                  {fmtCurrency(String(pl))}
                </TableCell>
                <TableCell className="text-right">
                  <form action={closeOptionAction}>
                    <input type="hidden" name="option_id" value={p.id} />
                    <button
                      type="submit"
                      className="rounded-md border px-2 py-0.5 text-xs hover:bg-accent"
                    >
                      Close
                    </button>
                  </form>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
