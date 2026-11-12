"use client";

/**
 * Ghost runs: the backtest proof.
 *
 * Thirty-six faint runs fan out first, each built by reshuffling the real
 * run's own daily returns (a bootstrap), so they show how much of the result
 * the order of the days decided. Then the real equity curve draws through them
 * beside buy-and-hold over the same window. Every line comes from one stored
 * backtest; the ghosts invent no returns, they only reorder the real ones.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  easeInOut,
  fitCanvas,
  readProofColors,
  seeded,
  span,
  useFrameLoop,
} from "@/components/marketing/proofs/canvas-loop";

const GHOSTS = 36;

function pct(v: number) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function GhostRuns({ strategy, benchmark }: { strategy: number[]; benchmark: number[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const model = useRef<ReturnType<typeof build> | null>(null);
  const colors = useRef<ProofColors | null>(null);

  useFrameLoop(canvasRef, {
    duration: 9,
    final: 6.2,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      model.current ??= build(strategy, benchmark);
      colors.current ??= readProofColors();
      paint(canvas, model.current, colors.current, t);
    },
  });

  return <canvas ref={canvasRef} aria-hidden className="absolute inset-0 size-full" />;
}

function build(strategy: number[], benchmark: number[]) {
  const n = strategy.length;
  const base = strategy[0];
  const real = strategy.map((v) => (v / base) * 100);
  const bench = benchmark.map((v) => (v / benchmark[0]) * 100);
  const returns = real.slice(1).map((v, i) => v / real[i] - 1);
  const ghosts = Array.from({ length: GHOSTS }, (_, k) => {
    const random = seeded(101 + k);
    const out = [100];
    for (let i = 1; i < n; i++) {
      out.push(out[i - 1] * (1 + returns[Math.floor(random() * returns.length)]));
    }
    return out;
  });
  // The middle 80% of the ghosts at each step, drawn as a soft band.
  const band = real.map((_, i) => {
    const column = ghosts.map((g) => g[i]).sort((a, b) => a - b);
    return [column[Math.floor(GHOSTS * 0.1)], column[Math.ceil(GHOSTS * 0.9) - 1]] as const;
  });
  let lo = Number.POSITIVE_INFINITY;
  let hi = Number.NEGATIVE_INFINITY;
  // Scale to the real lines and the middle band, not the outlier ghosts, which
  // may run off the top or bottom of the picture.
  for (const v of [...real, ...bench, ...band.flat()]) {
    lo = Math.min(lo, v);
    hi = Math.max(hi, v);
  }
  return { n, real, bench, ghosts, band, lo, hi };
}

function paint(canvas: HTMLCanvasElement, m: ReturnType<typeof build>, c: ProofColors, t: number) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const X = (i: number) => 16 + (i / (m.n - 1)) * (w - 32);
  const Y = (v: number) => 14 + (1 - (v - m.lo) / (m.hi - m.lo || 1)) * (h - 50);
  const line = (values: number[], count: number) => {
    ctx.beginPath();
    for (let i = 0; i < count; i++) {
      if (i === 0) ctx.moveTo(X(i), Y(values[i]));
      else ctx.lineTo(X(i), Y(values[i]));
    }
  };

  ctx.strokeStyle = c.line;
  ctx.lineWidth = 1;
  for (let k = 1; k < 4; k++) {
    const y = Math.round(((h - 36) * k) / 4) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  const fan = easeInOut(span(t, 0.2, 2.6));
  const count = Math.max(2, Math.floor(fan * m.n));
  ctx.fillStyle = c.brandFrom;
  ctx.globalAlpha = 0.14 * fan;
  ctx.beginPath();
  for (let i = 0; i < count; i++) ctx.lineTo(X(i), Y(m.band[i][1]));
  for (let i = count - 1; i >= 0; i--) ctx.lineTo(X(i), Y(m.band[i][0]));
  ctx.fill();

  ctx.strokeStyle = c.brandFrom;
  ctx.globalAlpha = 0.3 * (1 - 0.7 * span(t, 2.6, 3.8));
  for (const ghost of m.ghosts) {
    line(ghost, count);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  const draw = easeInOut(span(t, 2.6, 5.4));
  const shown = Math.max(2, Math.floor(draw * m.n));
  if (draw > 0) {
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = c.muted;
    ctx.lineWidth = 1.3;
    line(m.bench, shown);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.save();
    ctx.shadowColor = c.brand;
    ctx.shadowBlur = 14;
    ctx.strokeStyle = c.brand;
    ctx.lineWidth = 2.2;
    line(m.real, shown);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = c.brand;
    ctx.beginPath();
    ctx.arc(X(shown - 1), Y(m.real[shown - 1]), 3.5, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.font = `500 12px ${MONO_FONT}`;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillStyle = c.brand;
  ctx.fillText(`Strategy ${draw > 0 ? pct(m.real[shown - 1] - 100) : "…"}`, 16, h - 12);
  ctx.fillStyle = c.muted;
  ctx.fillText(`Buy and hold ${draw > 0 ? pct(m.bench[shown - 1] - 100) : "…"}`, 150, h - 12);
  if (w > 420) {
    ctx.textAlign = "right";
    ctx.fillText(`${GHOSTS} reshuffled runs`, w - 16, h - 12);
  }
}
