/**
 * A7.13 (M5.2): lender mode on the stock page's Financials tab. For a bank or
 * NBFC: P/B against ROE beside its market's financial peers (an SVG scatter
 * with the least-squares line), the gap to that line, and the justified P/B
 * at stated inputs. The missing lender KPIs are named, never invented.
 */

import type { Lender } from "@/lib/api/fundamentals";

const W = 320;
const H = 180;
const PAD = 28;

export function lenderScatter(data: Lender) {
  const pts = data.peers;
  if (pts.length === 0) return null;
  const xs = pts.map((p) => p.roe);
  const ys = pts.map((p) => p.pb);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [0, Math.max(...ys) * 1.1];
  const sx = (x: number) => PAD + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
  const sy = (y: number) => H - PAD - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * PAD);
  const line =
    data.slope != null && data.intercept != null
      ? {
          x1: sx(x0),
          y1: sy(data.intercept + data.slope * x0),
          x2: sx(x1),
          y2: sy(data.intercept + data.slope * x1),
        }
      : null;
  return { pts: pts.map((p) => ({ ...p, cx: sx(p.roe), cy: sy(p.pb) })), line };
}

export function LenderCard({ lender }: { lender: Lender | null }) {
  if (!lender) return null;
  const plot = lenderScatter(lender);
  return (
    <section aria-labelledby="lender-mode" className="space-y-3" data-testid="lender-card">
      <h2 id="lender-mode" className="text-base font-semibold">
        Lender Mode: P/B Against ROE
      </h2>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        {(
          [
            ["P/B", lender.pb?.toFixed(2)],
            ["ROE", lender.roe != null ? `${lender.roe.toFixed(1)}%` : null],
            ["Peer Line P/B", lender.line_pb?.toFixed(2)],
            [
              "Gap to the Line",
              lender.gap != null ? `${lender.gap > 0 ? "+" : ""}${lender.gap.toFixed(2)}` : null,
            ],
            [
              `Justified P/B (COE ${(lender.coe * 100).toFixed(0)}%, g ${(lender.growth * 100).toFixed(0)}%)`,
              lender.justified_pb?.toFixed(2),
            ],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt className="text-2xs text-text-tertiary">{label}</dt>
            <dd className="font-mono tabular-nums" data-testid="lender-figure">
              {value ?? "—"}
            </dd>
          </div>
        ))}
      </dl>
      {plot ? (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full max-w-md text-text-tertiary"
          role="img"
          aria-label={`P/B against ROE for ${lender.peers.length} financial peers`}
          data-testid="lender-scatter"
        >
          {plot.line ? (
            <line {...plot.line} stroke="currentColor" strokeDasharray="4 3" strokeWidth={1} />
          ) : null}
          {plot.pts.map((p) => (
            <circle
              key={p.ticker}
              cx={p.cx}
              cy={p.cy}
              r={p.ticker === lender.ticker ? 5 : 3}
              className={p.ticker === lender.ticker ? "fill-brand" : "fill-current"}
            >
              <title>{`${p.ticker}: P/B ${p.pb.toFixed(2)}, ROE ${p.roe.toFixed(1)}%`}</title>
            </circle>
          ))}
          <text x={PAD} y={H - 6} className="fill-current text-[9px]">
            ROE %
          </text>
          <text x={4} y={PAD - 10} className="fill-current text-[9px]">
            P/B
          </text>
        </svg>
      ) : null}
      {lender.reasons.map((r) => (
        <p key={r} className="text-xs text-text-secondary">
          {r}
        </p>
      ))}
      <p className="text-2xs text-text-tertiary">{lender.kpi_note}</p>
      <p className="text-2xs text-text-tertiary">{lender.method}</p>
    </section>
  );
}
