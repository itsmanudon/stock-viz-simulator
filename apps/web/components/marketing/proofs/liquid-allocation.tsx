"use client";

/**
 * Liquid allocation: the portfolio proof.
 *
 * An example account's holdings orbit its cash as liquid drops, sized by their
 * share of the account. They drift into the cash pool and pull away again (an
 * SVG "goo" filter merges shapes that touch), and every few seconds they
 * swell or shrink between the split on the day the example was bought and the
 * split at the latest close. Both splits come from real stored closes; the
 * account itself is an example, and the section says so.
 */

import { useId, useRef } from "react";

import { easeInOut, lerp, span, useFrameLoop } from "@/components/marketing/proofs/canvas-loop";

export type Drop = { ticker: string; start: number; now: number };

const CX = 200;
const CY = 125;

export function LiquidAllocation({
  drops,
  cash,
  startLabel,
  nowLabel,
}: {
  drops: Drop[];
  cash: { start: number; now: number };
  startLabel: string;
  nowLabel: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  // Unique ids, so two of these on one page never share a filter.
  const id = useId().replace(/:/g, "");

  useFrameLoop(svgRef, {
    duration: 10,
    final: 6,
    draw: (t) => {
      const svg = svgRef.current;
      if (!svg) return;
      const k = easeInOut(span(t, 3.5, 5)) - easeInOut(span(t, 8.6, 10));
      const circles = svg.querySelectorAll<SVGCircleElement>("[data-drop]");
      const labels = svg.querySelectorAll<SVGTextElement>("[data-label]");
      drops.forEach((drop, i) => {
        const weight = lerp(drop.start, drop.now, k);
        const r = 8 + Math.sqrt(weight) * 44;
        const angle = (i / drops.length) * Math.PI * 2 + t * 0.32;
        const orbit = 78 + Math.sin(t * 0.9 + i * 1.7) * 26;
        const x = CX + Math.cos(angle) * orbit * 1.35;
        const y = CY + Math.sin(angle) * orbit * 0.78;
        circles[i]?.setAttribute("cx", x.toFixed(1));
        circles[i]?.setAttribute("cy", y.toFixed(1));
        circles[i]?.setAttribute("r", r.toFixed(1));
        const label = labels[i];
        if (label) {
          label.setAttribute("x", x.toFixed(1));
          label.setAttribute("y", (y + r + 13).toFixed(1));
          label.textContent = `${drop.ticker} ${Math.round(weight * 100)}%`;
        }
      });
      const pool = svg.querySelector<SVGCircleElement>("[data-pool]");
      const weight = lerp(cash.start, cash.now, k);
      pool?.setAttribute("r", (14 + Math.sqrt(weight) * 44).toFixed(1));
      const poolLabel = svg.querySelector<SVGTextElement>("[data-pool-label]");
      if (poolLabel) poolLabel.textContent = `CASH ${Math.round(weight * 100)}%`;
      const when = svg.querySelector<SVGTextElement>("[data-when]");
      if (when) when.textContent = k > 0.5 ? nowLabel : startLabel;
    },
  });

  return (
    <svg
      ref={svgRef}
      aria-hidden="true"
      viewBox="0 0 400 250"
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 size-full"
    >
      <defs>
        <filter id={`${id}-goo`}>
          <feGaussianBlur in="SourceGraphic" stdDeviation="9" result="blur" />
          <feColorMatrix
            in="blur"
            mode="matrix"
            values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"
          />
        </filter>
        <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand-gradient-via)" />
          <stop offset="1" stopColor="var(--brand-gradient-from)" />
        </linearGradient>
      </defs>
      <g filter={`url(#${id}-goo)`} fill={`url(#${id}-fill)`}>
        <circle data-pool cx={CX} cy={CY} r="30" />
        {drops.map((drop) => (
          <circle key={drop.ticker} data-drop cx={CX} cy={CY} r="10" />
        ))}
      </g>
      <g fontFamily="var(--font-mono)" fontSize="10.5" textAnchor="middle">
        <text data-pool-label x={CX} y={CY + 4} fill="var(--background)" fontWeight="600">
          CASH
        </text>
        {drops.map((drop) => (
          <text key={drop.ticker} data-label fill="var(--foreground)" />
        ))}
        <text data-when x="10" y="240" textAnchor="start" fill="var(--text-tertiary)" />
      </g>
    </svg>
  );
}
