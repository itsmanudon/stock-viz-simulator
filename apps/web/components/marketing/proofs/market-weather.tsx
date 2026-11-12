"use client";

/**
 * Market weather: a slow aurora behind the hero and the closing call to
 * action, coloured by the last session's breadth.
 *
 * `share` is the fraction of tracked symbols whose latest close was up (from
 * the markets summary, counting only symbols with a dated move). More up
 * gives a greener sky, more down a redder one, with the brand aqua between.
 * Green and red keep their meaning here: they show gains and losses. The
 * figure itself is written beside it as text; this is only atmosphere, kept
 * faint so it never competes with the copy over it.
 */

import { useRef } from "react";

import {
  type ProofColors,
  clamp,
  fitCanvas,
  readProofColors,
  seeded,
  useFrameLoop,
} from "@/components/marketing/proofs/canvas-loop";
import { cn } from "@/lib/utils";

type Blob = {
  ax: number;
  ay: number;
  fx: number;
  fy: number;
  phase: number;
  size: number;
  k: number;
};

function hexRgb(hex: string): [number, number, number] {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return [56, 200, 240];
  const n = Number.parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function MarketWeather({
  share,
  strength = 0.1,
  className,
}: {
  share: number;
  /** Peak opacity of each light; keep it low behind text. */
  strength?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useRef<ProofColors | null>(null);
  const blobs = useRef<Blob[] | null>(null);

  useFrameLoop(canvasRef, {
    duration: 600,
    final: 8,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      if (!blobs.current) {
        const random = seeded(70);
        blobs.current = Array.from({ length: 6 }, (_, i) => ({
          ax: 0.25 + random() * 0.35,
          ay: 0.15 + random() * 0.3,
          fx: 0.05 + random() * 0.06,
          fy: 0.04 + random() * 0.05,
          phase: random() * 6,
          size: 0.35 + random() * 0.25,
          k: (i + 0.5) / 6,
        }));
      }
      paint(canvas, blobs.current, colors.current, share, strength, t);
    },
  });

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      // Fades out at every edge, so the sky never shows a box.
      style={{
        maskImage: "radial-gradient(ellipse 60% 55% at 50% 45%, black 35%, transparent 100%)",
      }}
      className={cn("pointer-events-none absolute -z-10", className ?? "inset-0 size-full")}
    />
  );
}

function paint(
  canvas: HTMLCanvasElement,
  blobs: Blob[],
  c: ProofColors,
  share: number,
  strength: number,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const up = hexRgb(c.pos);
  const down = hexRgb(c.neg);
  const mid = hexRgb(c.brand);
  ctx.globalCompositeOperation = "lighter";
  for (const b of blobs) {
    const cx = w * (0.5 + Math.sin(t * b.fx + b.phase) * b.ax);
    const cy = h * (0.35 + Math.cos(t * b.fy + b.phase) * b.ay);
    const radius = Math.max(w, h) * b.size;
    // Lights below the share lean green, the rest red; the ones near the
    // boundary stay brand aqua, so an even day reads as calm.
    const m = clamp((share - b.k) * 5, -1, 1);
    const target = m >= 0 ? up : down;
    const rgb = mid.map((v, j) => Math.round(v + (target[j] - v) * Math.abs(m)));
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
    g.addColorStop(0, `rgba(${rgb.join(",")},${strength})`);
    g.addColorStop(1, `rgba(${rgb.join(",")},0)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }
  ctx.globalCompositeOperation = "source-over";
}
