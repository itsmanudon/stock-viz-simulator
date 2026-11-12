"use client";

/**
 * Exploded candle: one stored daily bar taken apart and put back together.
 *
 * The upper wick lifts, the lower wick drops, and leader lines name the high,
 * close, open and low with their values, then the parts click back together.
 * It teaches how to read a candle in a few seconds. The values are one real
 * stored bar, and the caption beside it states them in text.
 */

import { useRef } from "react";

import { easeInOut, lerp, span, useFrameLoop } from "@/components/marketing/proofs/canvas-loop";

export type CandleBar = { open: number; high: number; low: number; close: number };

export function ExplodedCandle({ bar }: { bar: CandleBar }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const up = bar.close >= bar.open;
  const top = Math.max(bar.open, bar.close);
  const bottom = Math.min(bar.open, bar.close);
  const Y = (v: number) => 44 + (1 - (v - bar.low) / (bar.high - bar.low || 1)) * 140;
  const cx = 200;
  const parts = [
    { name: "High", value: bar.high, side: 1, wick: "up" },
    { name: up ? "Close" : "Open", value: top, side: -1, wick: "" },
    { name: up ? "Open" : "Close", value: bottom, side: -1, wick: "" },
    { name: "Low", value: bar.low, side: 1, wick: "down" },
  ] as const;

  useFrameLoop(svgRef, {
    duration: 7.5,
    final: 3.5,
    draw: (t) => {
      const svg = svgRef.current;
      if (!svg) return;
      const e = easeInOut(span(t, 0.8, 1.8)) * (1 - easeInOut(span(t, 5.6, 6.6)));
      const lift = 22 * e;
      svg.querySelector("[data-wick=up]")?.setAttribute("transform", `translate(0 ${-lift})`);
      svg.querySelector("[data-wick=down]")?.setAttribute("transform", `translate(0 ${lift})`);
      svg.querySelectorAll<SVGGElement>("[data-part]").forEach((g, i) => {
        const part = parts[i];
        const offset = part.wick === "up" ? -lift : part.wick === "down" ? lift : 0;
        const y = Y(part.value) + offset;
        const a = span(e, 0.3 + i * 0.12, 0.75 + i * 0.06);
        const x0 = cx + part.side * (part.wick ? 4 : 20);
        const x1 = cx + part.side * lerp(24, 92, a);
        const line = g.querySelector("line");
        const text = g.querySelector("text");
        line?.setAttribute("x1", String(x0));
        line?.setAttribute("x2", String(x1));
        line?.setAttribute("y1", String(y));
        line?.setAttribute("y2", String(y));
        text?.setAttribute("x", String(x1 + part.side * 6));
        text?.setAttribute("y", String(y + 4));
        g.setAttribute("opacity", a.toFixed(3));
      });
    },
  });

  const tone = up ? "var(--positive)" : "var(--negative)";
  return (
    <svg
      ref={svgRef}
      aria-hidden="true"
      viewBox="0 0 400 230"
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 size-full"
    >
      <line
        data-wick="up"
        x1={cx}
        x2={cx}
        y1={Y(bar.high)}
        y2={Y(top)}
        stroke={tone}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <rect
        x={cx - 18}
        width="36"
        y={Y(top)}
        height={Math.max(2, Y(bottom) - Y(top))}
        rx="3"
        fill={tone}
      />
      <line
        data-wick="down"
        x1={cx}
        x2={cx}
        y1={Y(bottom)}
        y2={Y(bar.low)}
        stroke={tone}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {parts.map((part) => (
        <g key={part.name} data-part opacity="0">
          <line stroke="var(--text-tertiary)" strokeWidth="1" strokeDasharray="2 3" />
          <text
            fontFamily="var(--font-mono)"
            fontSize="12"
            fill="var(--foreground)"
            textAnchor={part.side > 0 ? "start" : "end"}
          >
            {part.name.toUpperCase()} {part.value.toFixed(2)}
          </text>
        </g>
      ))}
    </svg>
  );
}
