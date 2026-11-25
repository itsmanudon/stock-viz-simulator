import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The PRISM mark: a faceted triangle whose three faces catch the brand's
 * violet, plasma and ion light, with a rising price line refracted through
 * it. Decorative, so the wordmark beside it carries the name.
 */
export function PrismMark({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    // biome-ignore lint/a11y/noSvgWithoutTitle: decorative; the wordmark beside it names the product
    <svg
      viewBox="0 0 32 32"
      aria-hidden
      className={cn("prism-mark size-7 shrink-0", className)}
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-a`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand-gradient-from)" />
          <stop offset="1" stopColor="var(--brand-gradient-via)" />
        </linearGradient>
        <linearGradient id={`${id}-b`} x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--brand-gradient-to)" />
          <stop offset="1" stopColor="var(--brand-gradient-from)" />
        </linearGradient>
      </defs>
      <path d="M16 3 L29 27 H3 Z" fill={`url(#${id}-a)`} opacity="0.95" />
      <path d="M16 3 L29 27 L16 20 Z" fill={`url(#${id}-b)`} opacity="0.9" />
      <path d="M3 27 L16 20 L29 27 Z" fill="#050507" opacity="0.35" />
      <path
        d="M6 22 L12 17 L16 19 L22 11 L27 8"
        fill="none"
        stroke="#fff"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.92"
      />
    </svg>
  );
}

/** Mark plus wordmark, as every header shows it. */
export function PrismWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <PrismMark />
      <span className="font-semibold tracking-[-0.02em]">
        Stock<span className="text-brand-gradient">Viz</span>
      </span>
    </span>
  );
}
