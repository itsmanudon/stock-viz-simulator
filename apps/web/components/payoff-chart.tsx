/**
 * A strategy's profit or loss across underlying prices (Phase 9.5): the
 * solid line at the first expiry, the dashed line today, the zero line,
 * today's close and the breakevens marked. Plain SVG coloured from tokens;
 * the figures it draws are stated in text beside it for screen readers.
 */

import type { PayoffPoint } from "@/lib/api/option-strategies";

const W = 480;
const H = 200;
const PAD = 4;

export function PayoffChart({
  points,
  spot,
  breakevens,
  horizon,
}: {
  points: PayoffPoint[];
  spot: number;
  breakevens: number[];
  horizon: string;
}) {
  if (points.length < 2) return null;
  const xs = points.map((p) => p.spot);
  const whatIf = points.some((p) => p.what_if !== null && p.what_if !== undefined);
  const ys = points.flatMap((p) => [p.at_expiry, p.today, ...(whatIf ? [p.what_if ?? 0] : [])]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(0, ...ys);
  const y1 = Math.max(0, ...ys);
  const ySpan = y1 - y0 || 1;
  const x = (v: number) => PAD + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
  const y = (v: number) => PAD + (1 - (v - y0) / ySpan) * (H - 2 * PAD);
  const path = (key: "at_expiry" | "today" | "what_if") =>
    points
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.spot).toFixed(1)},${y(p[key] ?? 0).toFixed(1)}`)
      .join(" ");
  const zero = y(0);
  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-48 w-full overflow-visible"
        role="img"
        aria-label={`Profit or loss by price at ${horizon} and today`}
      >
        <line x1={0} x2={W} y1={zero} y2={zero} className="stroke-border" strokeWidth={1} />
        <line
          x1={x(spot)}
          x2={x(spot)}
          y1={0}
          y2={H}
          className="stroke-text-tertiary"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
        {breakevens
          .filter((b) => b >= x0 && b <= x1)
          .map((b) => (
            <circle key={b} cx={x(b)} cy={zero} r={3} className="fill-brand" />
          ))}
        <path
          d={path("today")}
          fill="none"
          className="stroke-text-secondary"
          strokeWidth={1.5}
          strokeDasharray="5 4"
        />
        <path d={path("at_expiry")} fill="none" className="stroke-brand" strokeWidth={2} />
        {whatIf ? (
          <path
            d={path("what_if")}
            fill="none"
            className="stroke-warning"
            strokeWidth={1.5}
            strokeDasharray="1 3"
            data-testid="payoff-what-if"
          />
        ) : null}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-text-tertiary">
        <span>Solid: at {horizon}</span>
        <span>Dashed: today</span>
        {whatIf ? <span>Dotted: what-if</span> : null}
        <span>Dotted line: today&apos;s close</span>
        <span>Dots: breakevens</span>
      </figcaption>
    </figure>
  );
}
