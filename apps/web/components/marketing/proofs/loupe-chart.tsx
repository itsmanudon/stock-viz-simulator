"use client";

/**
 * Loupe: a candlestick chart of stored daily bars with a jeweller's loupe.
 *
 * Point at the chart and the loupe magnifies the candles under it and reads
 * out that day's open, high, low and close. Nobody pointing, it drifts along
 * the closes by itself. The readout is the one interactive part; the canvas
 * stays aria-hidden because the section states the range and the latest bar
 * in text, and a pointer readout is not the only way to reach any figure.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  clamp,
  fitCanvas,
  readProofColors,
  useFrameLoop,
} from "@/components/marketing/proofs/canvas-loop";

export type LoupeBar = { date: string; open: number; high: number; low: number; close: number };

const ZOOM = 3;

export function LoupeChart({ bars }: { bars: LoupeBar[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useRef<ProofColors | null>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);

  useFrameLoop(canvasRef, {
    duration: 600,
    final: 3,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      paint(canvas, bars, colors.current, pointer.current, t);
    },
  });

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="absolute inset-0 size-full cursor-crosshair"
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        pointer.current = { x: event.clientX - box.left, y: event.clientY - box.top };
      }}
      onPointerLeave={() => {
        pointer.current = null;
      }}
    />
  );
}

function paint(
  canvas: HTMLCanvasElement,
  bars: LoupeBar[],
  c: ProofColors,
  pointer: { x: number; y: number } | null,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const n = bars.length;
  const lo = Math.min(...bars.map((b) => b.low));
  const hi = Math.max(...bars.map((b) => b.high));
  const X = (i: number) => 12 + ((i + 0.5) / n) * (w - 24);
  const Y = (v: number) => 14 + (1 - (v - lo) / (hi - lo || 1)) * (h - 48);
  const bodyW = Math.max(1, ((w - 24) / n) * 0.6);

  const candles = (lineWidth: number) => {
    bars.forEach((b, i) => {
      const color = b.close >= b.open ? c.pos : c.neg;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.beginPath();
      ctx.moveTo(X(i), Y(b.high));
      ctx.lineTo(X(i), Y(b.low));
      ctx.stroke();
      const top = Y(Math.max(b.open, b.close));
      ctx.fillRect(X(i) - bodyW / 2, top, bodyW, Math.max(1, Y(Math.min(b.open, b.close)) - top));
    });
  };

  ctx.strokeStyle = c.line;
  ctx.lineWidth = 1;
  for (let k = 1; k < 4; k++) {
    const y = Math.round(((h - 34) * k) / 4) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  ctx.globalAlpha = 0.55;
  candles(1);
  ctx.globalAlpha = 1;

  let px: number;
  let py: number;
  if (pointer) {
    // Follow the pointer along the dates, but sit on that day's close so the
    // glass always has candles under it.
    px = pointer.x;
    const i = clamp(Math.round(((px - 12) / (w - 24)) * n - 0.5), 0, n - 1);
    py = Y(bars[i].close);
  } else {
    const at = (0.5 + 0.5 * Math.sin(t * 0.45)) * (n - 1);
    px = X(at);
    py = Y(bars[Math.round(at)].close);
  }
  const index = clamp(Math.round(((px - 12) / (w - 24)) * n - 0.5), 0, n - 1);
  const bar = bars[index];
  const radius = Math.min(62, h * 0.24);
  // Keep the whole glass inside the chart, clear of the readout.
  py = clamp(py, radius + 6, h - 34 - radius);

  ctx.save();
  ctx.beginPath();
  ctx.arc(px, py, radius, 0, Math.PI * 2);
  ctx.clip();
  ctx.fillStyle = c.card;
  ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
  ctx.translate(px, py);
  ctx.scale(ZOOM, ZOOM);
  ctx.translate(-px, -py);
  candles(1 / ZOOM);
  ctx.restore();
  ctx.strokeStyle = c.fg;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(px, py, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 0.18;
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(px, py, radius + 4, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;

  const f = (v: number) => v.toFixed(2);
  const text = `${bar.date}  O ${f(bar.open)}  H ${f(bar.high)}  L ${f(bar.low)}  C ${f(bar.close)}`;
  ctx.font = `500 11px ${MONO_FONT}`;
  const tw = ctx.measureText(text).width;
  const bx = clamp(px - tw / 2 - 10, 6, w - tw - 26);
  ctx.beginPath();
  ctx.roundRect(bx, h - 27, tw + 20, 21, 10);
  ctx.fillStyle = c.card;
  ctx.fill();
  ctx.strokeStyle = c.line;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = c.fg;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillText(text, bx + 10, h - 12.5);
}
