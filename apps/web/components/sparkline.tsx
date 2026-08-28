/**
 * Tiny SVG sparkline rendered server-side from a series of closes.
 *
 * No axes, tooltips, or interactivity. Stroke flips to the positive token when
 * the last close is above the baseline, negative otherwise — server-rendered,
 * so it reads the tokens through a Tailwind text colour rather than the
 * runtime palette the canvas charts use. Fewer than two closes yields an empty
 * placeholder so layout stays stable when the API has no bars to return yet.
 *
 * A dashed baseline marks the opening close of the window, the reference every
 * finance site draws: without it a sparkline shows the shape of a move but not
 * whether the symbol is actually up or down over the period, since the y-axis
 * is auto-scaled to the series. The area between the line and the baseline is
 * filled so the direction reads at a glance.
 */

import { useId } from "react";

import { cn } from "@/lib/utils";

type Props = {
  closes: number[];
  width?: number;
  height?: number;
  className?: string;
  /**
   * Reference level for the dashed line. Defaults to the first close, i.e.
   * "where this started". Pass a previous close for a day-change reading.
   */
  baseline?: number | null;
  /** Set false for the densest contexts, where the extra ink hurts. */
  showBaseline?: boolean;
  /** Days the series covers; only used for the accessible label. */
  periodLabel?: string;
};

export function Sparkline({
  closes,
  width = 100,
  height = 28,
  className,
  baseline,
  showBaseline = true,
  periodLabel = "30-day",
}: Props) {
  const gradientId = useId();
  const clipId = useId();

  if (closes.length < 2) {
    return (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className={className}
        role="img"
        aria-label="no data"
      >
        <title>No sparkline data</title>
      </svg>
    );
  }

  const reference = baseline ?? closes[0];
  // The baseline participates in the scale, otherwise it can sit outside the
  // drawn area when the whole series moved away from it.
  const min = Math.min(...closes, reference);
  const max = Math.max(...closes, reference);
  const span = max - min || 1;

  // Inset vertically so the stroke and the baseline never clip on the edges.
  const inset = 1.5;
  const usable = height - inset * 2;
  const stepX = width / (closes.length - 1);
  const toY = (value: number) => inset + usable - ((value - min) / span) * usable;

  const points = closes.map(
    (close, index) => `${(index * stepX).toFixed(2)},${toY(close).toFixed(2)}`,
  );
  const line = `M${points.join(" L")}`;
  const baselineY = toY(reference);
  // Close the path along the baseline so the fill shows the gap from it.
  const area = `${line} L${width.toFixed(2)},${baselineY.toFixed(2)} L0,${baselineY.toFixed(2)} Z`;

  const up = closes[closes.length - 1] >= reference;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="none"
      className={cn(up ? "text-positive" : "text-negative", className)}
      role="img"
      aria-label={`${periodLabel} price sparkline, ${up ? "up" : "down"} against its opening level`}
    >
      <title>{`${periodLabel} price trend`}</title>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.02" />
        </linearGradient>
        <clipPath id={clipId}>
          <rect x="0" y="0" width={width} height={height} />
        </clipPath>
      </defs>

      <g clipPath={`url(#${clipId})`}>
        <path d={area} fill={`url(#${gradientId})`} />
        {showBaseline ? (
          <line
            x1="0"
            y1={baselineY}
            x2={width}
            y2={baselineY}
            stroke="currentColor"
            strokeWidth="1"
            strokeDasharray="3 3"
            strokeOpacity="0.45"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        <path
          d={line}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </g>
    </svg>
  );
}
