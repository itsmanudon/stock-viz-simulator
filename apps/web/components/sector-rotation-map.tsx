/**
 * The sector rotation map (A7.2, M3.2): each sector's last weeks of
 * RS-Trend (x) against RS-Momentum (y), both centred on 100, with the four
 * quadrants. Plain SVG; the maths is the API's (`/v1/sector-rotation`),
 * openly documented and not RRG®.
 */

import type { Rotation } from "@/lib/api/sector-rotation";

const SIZE = 320;
const PAD = 28;
const QUADRANTS = [
  { label: "Improving", x: PAD + 6, y: PAD + 14 },
  { label: "Leading", x: SIZE - PAD - 6, y: PAD + 14, end: true },
  { label: "Lagging", x: PAD + 6, y: SIZE - PAD - 8 },
  { label: "Weakening", x: SIZE - PAD - 6, y: SIZE - PAD - 8, end: true },
];
const COLOURS = [
  "var(--color-brand)",
  "var(--color-positive)",
  "var(--color-negative)",
  "var(--color-warning)",
  "var(--color-text-secondary)",
  "var(--color-text-tertiary)",
];

/** The axis half-span: the furthest point from 100, at least 2, rounded up. */
export function rotationSpan(rotation: Rotation): number {
  let span = 2;
  for (const s of rotation.sectors) {
    for (const p of s.points) {
      span = Math.max(span, Math.abs(p.rs_trend - 100), Math.abs(p.rs_momentum - 100));
    }
  }
  return Math.ceil(span * 1.1);
}

export function SectorRotationMap({ rotation }: { rotation: Rotation }) {
  if (rotation.sectors.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        Not enough sector history for a rotation map yet (a sector needs 3 members and {14} weeks of
        bars).
      </p>
    );
  }
  const span = rotationSpan(rotation);
  const scale = (v: number) => PAD + ((v - (100 - span)) / (2 * span)) * (SIZE - 2 * PAD);
  const x = (trend: number) => scale(trend);
  const y = (momentum: number) => SIZE - scale(momentum);
  const mid = scale(100);
  return (
    <figure className="space-y-2" data-testid={`rotation-${rotation.market}`}>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="h-auto w-full max-w-sm"
        role="img"
        aria-label={`Sector rotation, ${rotation.market}, against ${rotation.benchmark_name}`}
      >
        <rect
          x={PAD}
          y={PAD}
          width={SIZE - 2 * PAD}
          height={SIZE - 2 * PAD}
          fill="none"
          stroke="var(--color-border-muted)"
        />
        <line x1={mid} x2={mid} y1={PAD} y2={SIZE - PAD} stroke="var(--color-border-muted)" />
        <line
          x1={PAD}
          x2={SIZE - PAD}
          y1={SIZE - mid}
          y2={SIZE - mid}
          stroke="var(--color-border-muted)"
        />
        {QUADRANTS.map((q) => (
          <text
            key={q.label}
            x={q.x}
            y={q.y}
            fontSize={10}
            fill="var(--color-text-tertiary)"
            textAnchor={q.end ? "end" : "start"}
          >
            {q.label}
          </text>
        ))}
        <text
          x={SIZE / 2}
          y={SIZE - 6}
          fontSize={10}
          textAnchor="middle"
          fill="var(--color-text-tertiary)"
        >
          RS-Trend →
        </text>
        <text
          x={10}
          y={SIZE / 2}
          fontSize={10}
          textAnchor="middle"
          fill="var(--color-text-tertiary)"
          transform={`rotate(-90 10 ${SIZE / 2})`}
        >
          RS-Momentum →
        </text>
        {rotation.sectors.map((s, i) => {
          const colour = COLOURS[i % COLOURS.length];
          const pts = s.points.map((p) => `${x(p.rs_trend)},${y(p.rs_momentum)}`).join(" ");
          const last = s.points[s.points.length - 1];
          return (
            <g key={s.sector}>
              <polyline
                points={pts}
                fill="none"
                stroke={colour}
                strokeWidth={1.25}
                strokeOpacity={0.7}
              />
              <circle cx={x(last.rs_trend)} cy={y(last.rs_momentum)} r={3.5} fill={colour}>
                <title>{`${s.sector}: trend ${last.rs_trend}, momentum ${last.rs_momentum} (${last.quadrant}), week of ${last.week}`}</title>
              </circle>
              <text x={x(last.rs_trend) + 5} y={y(last.rs_momentum) - 5} fontSize={9} fill={colour}>
                {s.sector}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="text-xs text-text-tertiary">
        Against {rotation.benchmark_name}, weekly, {rotation.sectors[0]?.points.length ?? 0}-week
        trails{rotation.as_of ? `, to ${rotation.as_of}` : ""}. {rotation.note}
      </figcaption>
    </figure>
  );
}
