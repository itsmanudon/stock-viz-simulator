import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The StockViz mark (Liquid Chrome, Nov 2026): one polished-metal candle in a
 * black-titanium tile. Every price in StockViz is a stored daily close, so the
 * mark is a single close; the champagne cap is the close at the top of the
 * body. A thin glint crosses the tile on hover (`.stockviz-mark` in
 * globals.css), never on its own, and never with reduced motion.
 *
 * Decorative, so the wordmark beside it carries the name. `app/icon.svg` is
 * the same drawing for the favicon; change both together.
 */
export function StockVizMark({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  const metal = `${id}-metal`;
  const cap = `${id}-cap`;
  const tile = `${id}-tile`;
  const clip = `${id}-clip`;
  return (
    // biome-ignore lint/a11y/noSvgWithoutTitle: decorative; the wordmark beside it names the product
    <svg
      viewBox="0 0 32 32"
      aria-hidden
      className={cn("stockviz-mark size-7 shrink-0", className)}
      focusable="false"
    >
      <defs>
        <linearGradient id={metal} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f7f8fa" />
          <stop offset="0.35" stopColor="var(--brand-gradient-from)" />
          <stop offset="0.6" stopColor="var(--brand-gradient-to)" />
          <stop offset="1" stopColor="#5d6676" />
        </linearGradient>
        <linearGradient id={cap} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff6e2" />
          <stop offset="1" stopColor="var(--brand)" />
        </linearGradient>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2a2c31" />
          <stop offset="0.5" stopColor="#121316" />
          <stop offset="1" stopColor="#1d1e22" />
        </linearGradient>
        <clipPath id={clip}>
          <rect x="1" y="1" width="30" height="30" rx="9" />
        </clipPath>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill={`url(#${tile})`} />
      <rect
        x="1.5"
        y="1.5"
        width="29"
        height="29"
        rx="8.5"
        fill="none"
        stroke={`url(#${metal})`}
        strokeOpacity="0.55"
      />
      <rect x="15.1" y="6" width="1.8" height="20" rx="0.9" fill={`url(#${metal})`} />
      <rect x="11.5" y="10" width="9" height="12" rx="2.2" fill={`url(#${metal})`} />
      <rect x="11.5" y="10" width="9" height="2.6" rx="1.3" fill={`url(#${cap})`} />
      <g clipPath={`url(#${clip})`}>
        <rect
          className="stockviz-mark-glint"
          x="4"
          y="-4"
          width="3"
          height="40"
          fill="#fff"
          opacity="0.18"
          transform="rotate(20 16 16)"
        />
      </g>
    </svg>
  );
}

/** Mark plus wordmark, as every header and the footer show it. */
export function StockVizWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("group/mark flex items-center gap-2.5", className)}>
      <StockVizMark />
      <span className="font-semibold tracking-[-0.02em]">
        Stock<span className="text-brand-gradient">Viz</span>
      </span>
    </span>
  );
}
