import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * Server-rendered filled area sparkline for the dashboard hero.
 *
 * Deliberately not `equity-curve.tsx`: that pulls lightweight-charts into the
 * client bundle for a chart the dashboard shows at a glance and never lets you
 * interact with. Colour comes from `currentColor`, so callers tint it with a
 * `text-positive` / `text-negative` class rather than hard-coded hex.
 */
export function NavSparkline({
  values,
  width = 640,
  height = 96,
  className,
  label,
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  label: string;
}) {
  const gradientId = useId();

  if (values.length < 2) {
    return (
      <div
        className={cn("flex items-center justify-center text-xs text-text-tertiary", className)}
        style={{ minHeight: height / 2 }}
      >
        Not enough history to chart yet
      </div>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);

  // Pad vertically so the stroke never clips against the viewBox edges.
  const inset = 2;
  const usable = height - inset * 2;
  const points = values.map((value, index) => {
    const x = index * stepX;
    const y = inset + usable - ((value - min) / span) * usable;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const line = `M${points.join(" L")}`;
  const area = `${line} L${width.toFixed(2)},${height} L0,${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("w-full", className)}
      style={{ height }}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
