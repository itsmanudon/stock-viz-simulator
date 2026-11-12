"use client";

/**
 * Rebase snap: the compare proof.
 *
 * Two symbols first draw on their own price scales, in their own currencies,
 * one above the other, where they cannot be compared. Then both spring onto
 * one index that starts at 100 on the first shared day, overshoot a little,
 * settle, and show their returns. The spring acts on the axis itself, which is
 * what Compare does: it rebases, it does not convert.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  easeInOut,
  fitCanvas,
  lerp,
  readProofColors,
  span,
  useFrameLoop,
} from "@/components/marketing/proofs/canvas-loop";

export type RebaseSeries = { ticker: string; symbol: string; closes: number[] };

const SNAP_AT = 2.4;

/** A damped spring from 0 to 1, `u` seconds after release. */
function spring(u: number) {
  return 1 - Math.exp(-6 * u) * Math.cos(10 * u);
}

export function RebaseSnap({ a, b }: { a: RebaseSeries; b: RebaseSeries }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useRef<ProofColors | null>(null);

  useFrameLoop(canvasRef, {
    duration: 8.5,
    final: 7,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      paint(canvas, a, b, colors.current, t);
    },
  });

  return <canvas ref={canvasRef} aria-hidden className="absolute inset-0 size-full" />;
}

function paint(
  canvas: HTMLCanvasElement,
  a: RebaseSeries,
  b: RebaseSeries,
  c: ProofColors,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const n = a.closes.length;
  const index = (s: number[]) => s.map((v) => (v / s[0]) * 100);
  const ia = index(a.closes);
  const ib = index(b.closes);
  const all = [...ia, ...ib];
  const ilo = Math.min(...all);
  const ihi = Math.max(...all);
  const range = (s: number[]) => [Math.min(...s), Math.max(...s)] as const;
  const [aLo, aHi] = range(a.closes);
  const [bLo, bHi] = range(b.closes);
  const left = 64;
  const right = w > 480 ? 112 : 84;
  const X = (i: number) => left + (i / (n - 1)) * (w - left - right);
  const rawA = (v: number) => 20 + (1 - (v - aLo) / (aHi - aLo || 1)) * (h * 0.5 - 40);
  const rawB = (v: number) => h * 0.5 + 20 + (1 - (v - bLo) / (bHi - bLo || 1)) * (h * 0.5 - 50);
  const idx = (v: number) => 20 + (1 - (v - ilo) / (ihi - ilo || 1)) * (h - 60);

  const shown = Math.max(2, Math.floor(easeInOut(span(t, 0.2, 1.8)) * n));
  const m = t < SNAP_AT ? 0 : spring(t - SNAP_AT);
  const before = 1 - span(t, SNAP_AT, SNAP_AT + 0.5);

  ctx.font = `500 11px ${MONO_FONT}`;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  if (before > 0) {
    ctx.globalAlpha = before;
    ctx.fillStyle = c.muted;
    const fmt = (sym: string, v: number) => `${sym}${Math.round(v).toLocaleString("en-US")}`;
    ctx.fillText(fmt(a.symbol, aHi), 8, 26);
    ctx.fillText(fmt(a.symbol, aLo), 8, h * 0.5 - 18);
    ctx.fillText(fmt(b.symbol, bHi), 8, h * 0.5 + 26);
    ctx.fillText(fmt(b.symbol, bLo), 8, h - 28);
    ctx.strokeStyle = c.line;
    ctx.beginPath();
    ctx.moveTo(0, Math.round(h * 0.5) + 0.5);
    ctx.lineTo(w, Math.round(h * 0.5) + 0.5);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  if (m > 0) {
    const y100 = Math.round(idx(100)) + 0.5;
    ctx.globalAlpha = Math.min(1, m);
    ctx.setLineDash([3, 5]);
    ctx.strokeStyle = c.muted;
    ctx.beginPath();
    ctx.moveTo(left, y100);
    ctx.lineTo(w - right + 8, y100);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = c.muted;
    ctx.fillText("100", 26, y100 + 4);
    ctx.globalAlpha = 1;
  }

  const draw = (
    raw: number[],
    ind: number[],
    place: (v: number) => number,
    color: string,
    dash: number[],
  ) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dash);
    ctx.beginPath();
    for (let i = 0; i < shown; i++) {
      const y = lerp(place(raw[i]), idx(ind[i]), m);
      if (i === 0) ctx.moveTo(X(i), y);
      else ctx.lineTo(X(i), y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    return { x: X(shown - 1), y: lerp(place(raw[shown - 1]), idx(ind[shown - 1]), m) };
  };
  // Compare tells its series apart by dash as well as colour; so does this.
  const endA = draw(a.closes, ia, rawA, c.brand, []);
  const endB = draw(b.closes, ib, rawB, c.brandFrom, [6, 4]);

  const label = (end: { x: number; y: number }, s: RebaseSeries, ind: number[], color: string) => {
    ctx.font = `600 11px ${MONO_FONT}`;
    ctx.fillStyle = color;
    ctx.fillText(s.ticker, end.x + 8, end.y - 3);
    if (m > 0.6) {
      const r = ind[n - 1] - 100;
      ctx.globalAlpha = span(m, 0.6, 1);
      ctx.font = `500 11px ${MONO_FONT}`;
      ctx.fillStyle = r >= 0 ? c.pos : c.neg;
      ctx.fillText(`${r >= 0 ? "+" : ""}${r.toFixed(1)}%`, end.x + 8, end.y + 11);
      ctx.globalAlpha = 1;
    }
  };
  // The lower label goes second so it never hides under the other line's.
  const order = endA.y <= endB.y ? ([0, 1] as const) : ([1, 0] as const);
  for (const k of order) {
    if (k === 0) label(endA, a, ia, c.brand);
    else
      label(
        { x: endB.x, y: endB.y + (Math.abs(endA.y - endB.y) < 26 && m > 0.5 ? 14 : 0) },
        b,
        ib,
        c.brandFrom,
      );
  }
}
