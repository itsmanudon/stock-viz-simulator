"use client";

/**
 * The sieve: the screener proof.
 *
 * Every tracked symbol drops as a chip through the filter layers. A chip that
 * fails a layer is knocked aside and fades; the survivors settle into rows at
 * the bottom. Which chip stops where comes from real screener queries run on
 * the server, so the counts at each layer are the screener's own.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  easeOut,
  fitCanvas,
  lerp,
  readProofColors,
  seeded,
  useFrameLoop,
} from "@/components/marketing/proofs/canvas-loop";

export type SieveChip = {
  ticker: string;
  /** Index of the layer that rejects it, or `layers.length` for a survivor. */
  stopsAt: number;
};

const CHIP_H = 20;

export function Sieve({ layers, chips }: { layers: string[]; chips: SieveChip[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useRef<ProofColors | null>(null);
  const plan = useRef<ReturnType<typeof layout> | null>(null);

  useFrameLoop(canvasRef, {
    duration: 10,
    final: 9,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      plan.current ??= layout(chips);
      paint(canvas, layers, plan.current, colors.current, t);
    },
  });

  return <canvas ref={canvasRef} aria-hidden className="absolute inset-0 size-full" />;
}

function layout(chips: SieveChip[]) {
  const random = seeded(42);
  const spacing = Math.min(0.09, 4.5 / Math.max(chips.length, 1));
  return chips.map((chip, index) => ({
    ...chip,
    x: 0.04 + random() * 0.84,
    start: index * spacing + random() * 0.2,
    dir: random() < 0.5 ? -1 : 1,
  }));
}

function paint(
  canvas: HTMLCanvasElement,
  layers: string[],
  plan: ReturnType<typeof layout>,
  c: ProofColors,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const speed = h * 0.42;
  const chipW = Math.min(64, Math.max(48, w * 0.11));
  const floor = h * 0.8;
  const layerY = layers.map((_, i) => h * (0.2 + (0.52 * (i + 0.5)) / layers.length));
  const passed = layers.map(() => 0);
  const survivors = plan.filter((p) => p.stopsAt === layers.length);
  const perRow = Math.max(1, Math.floor((w - 24) / (chipW + 8)));

  const placed = plan.map((p) => {
    const age = t - p.start;
    if (age < 0) return null;
    let y = -CHIP_H + age * speed;
    let x = p.x * (w - chipW);
    let alpha = 1;
    let turn = 0;
    let tone: "plain" | "out" | "kept" = "plain";
    for (let i = 0; i < layers.length; i++) {
      const top = layerY[i] - CHIP_H;
      if (y <= top) break;
      if (p.stopsAt === i) {
        const since = (y - top) / speed;
        x += p.dir * since * 150;
        y = top + since * speed * 0.35 + since * since * 40;
        alpha = Math.max(0, 1 - since * 1.4);
        turn = p.dir * since * 1.3;
        tone = "out";
        break;
      }
      passed[i]++;
    }
    if (p.stopsAt === layers.length && y > floor) {
      const settle = easeOut(Math.min(1, (y - floor) / (speed * 0.5)));
      const index = survivors.indexOf(p);
      const row = Math.floor(index / perRow);
      const inRow = Math.min(perRow, survivors.length - row * perRow);
      const col = index % perRow;
      const targetX = w / 2 + (col - (inRow - 1) / 2) * (chipW + 8) - chipW / 2;
      x = lerp(x, targetX, settle);
      y = lerp(floor, floor + 6 + row * (CHIP_H + 6), settle);
      tone = "kept";
    }
    return { x, y, alpha, turn, tone, ticker: p.ticker };
  });

  layers.forEach((label, i) => {
    const y = Math.round(layerY[i]) + 0.5;
    ctx.strokeStyle = c.line;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = `500 11px ${MONO_FONT}`;
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    ctx.fillStyle = c.muted;
    ctx.fillText(label, 10, y - 6);
    ctx.textAlign = "right";
    ctx.fillStyle = passed[i] ? c.fg : c.muted;
    ctx.fillText(`${passed[i]} pass`, w - 10, y - 6);
  });

  ctx.font = `600 10.5px ${MONO_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (const chip of placed) {
    if (!chip || chip.alpha <= 0) continue;
    ctx.save();
    ctx.globalAlpha = chip.alpha;
    ctx.translate(chip.x + chipW / 2, chip.y + CHIP_H / 2);
    ctx.rotate(chip.turn);
    ctx.beginPath();
    ctx.roundRect(-chipW / 2, -CHIP_H / 2, chipW, CHIP_H, 7);
    ctx.fillStyle = c.card;
    ctx.fill();
    ctx.strokeStyle = chip.tone === "kept" ? c.brand : chip.tone === "out" ? c.neg : c.line;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = chip.tone === "kept" ? c.brand : chip.tone === "out" ? c.muted : c.fg;
    const label = chip.ticker.length > 9 ? `${chip.ticker.slice(0, 8)}…` : chip.ticker;
    ctx.fillText(label, 0, 0.5);
    ctx.restore();
  }

  const counts = [plan.length, ...passed].filter((n, i) => i === 0 || n > 0);
  ctx.font = `500 12px ${MONO_FONT}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = c.brand;
  ctx.fillText(counts.join(" → "), 10, 18);
}
