/**
 * Plain words for each broker state (A5.7, M1.7). StockViz has no live
 * broker connection: Kite (Zerodha) only serves one-off price history
 * snapshots run by hand, and imported books update from an uploaded
 * tradebook (CSV, A5.3). Pure, so the copy is tested on its own.
 */

import type { BadgeTone } from "@/components/status-badge";
import { formatUtcDateTime } from "@/lib/api-time";

export type BrokerState = "not_configured" | "not_connected" | "offline" | "snapshot_only";

export type BrokerStatusLike = {
  label: string;
  state: BrokerState;
  imported_books: number;
  last_imported_at?: string | null;
  last_snapshot_at?: string | null;
  last_failure_at?: string | null;
};

export const IMPORT_LINE = "Imported books update when you upload a tradebook (CSV).";

export const BADGE: Record<BrokerState, { label: string; tone: BadgeTone }> = {
  not_configured: { label: "Not Set Up", tone: "neutral" },
  not_connected: { label: "Not Connected", tone: "neutral" },
  snapshot_only: { label: "Snapshots Only", tone: "brand" },
  offline: { label: "Offline", tone: "warning" },
};

export type BrokerCopy = {
  /** "Zerodha: not connected." */
  headline: string;
  /** What the state means for prices. */
  detail: string;
  /** How imported books update, plus their count when there are any. */
  imports: string;
  badge: { label: string; tone: BadgeTone };
};

export function brokerCopy(b: BrokerStatusLike): BrokerCopy {
  const name = b.label || "Zerodha";
  const headline =
    b.state === "offline"
      ? `${name}: offline.`
      : b.state === "snapshot_only"
        ? `${name}: snapshots only.`
        : `${name}: not connected.`;
  const detail = (() => {
    switch (b.state) {
      case "not_configured":
        return "Live broker data needs a paid Kite Connect app; not set up.";
      case "not_connected":
        return "A Kite Connect app is set up on this server for one-off price history snapshots; none has been taken yet. There is no live broker data.";
      case "snapshot_only":
        return `Kite is used only for one-off price history snapshots${b.last_snapshot_at ? `, last on ${formatUtcDateTime(b.last_snapshot_at)}` : ""}. There is no live broker data.`;
      case "offline":
        return `The last Kite snapshot failed${b.last_failure_at ? ` on ${formatUtcDateTime(b.last_failure_at)}` : ""}. Prices stay end of day from the nightly run.`;
    }
  })();
  let imports = IMPORT_LINE;
  if (b.imported_books > 0) {
    const books = b.imported_books === 1 ? "1 imported book" : `${b.imported_books} imported books`;
    imports += ` ${books}; last upload: ${b.last_imported_at ? formatUtcDateTime(b.last_imported_at) : "none yet"}.`;
  }
  return { headline, detail, imports, badge: BADGE[b.state] };
}

/** One line for tight spots (an imported book's empty state). */
export function brokerLine(b: BrokerStatusLike | null): string {
  if (!b) return `Zerodha: status unavailable. ${IMPORT_LINE}`;
  const c = brokerCopy(b);
  return `${c.headline} ${IMPORT_LINE}`;
}
