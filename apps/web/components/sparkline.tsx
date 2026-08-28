/**
 * Tiny SVG sparkline rendered server-side from a series of closes.
 *
 * Just a polyline, no axes / tooltips / interactivity. Stroke flips to the
 * positive token when the last close is above the first, negative otherwise —
 * server-rendered, so it reads the tokens through a Tailwind text colour
 * rather than the runtime palette the canvas charts use. Fewer than two
 * closes yields an empty placeholder so layout stays stable when the API has
 * no bars to return yet.
 */

import { cn } from "@/lib/utils";

type Props = {
  closes: number[];
  width?: number;
  height?: number;
  className?: string;
};

export function Sparkline({ closes, width = 100, height = 28, className }: Props) {
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

  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const stepX = width / (closes.length - 1);

  const points = closes
    .map((c, i) => {
      const x = i * stepX;
      // Invert Y: higher prices toward the top.
      const y = height - ((c - min) / span) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const up = closes[closes.length - 1] >= closes[0];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn(up ? "text-positive" : "text-negative", className)}
      role="img"
      aria-label={`30-day price sparkline, ${up ? "up" : "down"}`}
    >
      <title>30-day price trend</title>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
