"use client";

/**
 * Sonar sweep: the signals proof.
 *
 * A beam turns over a radar. Each symbol's blip pings as the beam passes, and
 * its distance from the centre is its vote count: more of the seven rules
 * passing puts it nearer the middle and makes the ping brighter. Every blip is
 * a real Signals row; the angle only spreads them out and means nothing.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  fitCanvas,
  readProofColors,
  seeded,
  useFrameLoop,
  withAlpha,
} from "@/components/marketing/proofs/canvas-loop";

export type SonarBlip = { ticker: string; score: number; max: number };

const PERIOD = 3.2;
const TAU = Math.PI * 2;

export function SonarSweep({ blips }: { blips: SonarBlip[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useRef<ProofColors | null>(null);
  const angles = useRef<number[] | null>(null);

  useFrameLoop(canvasRef, {
    duration: PERIOD * 4,
    final: PERIOD * 0.7,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      if (!angles.current) {
        // Even spacing with a small fixed wobble, so labels never stack.
        const random = seeded(9);
        angles.current = blips.map((_, i) => ((i + 0.15 * random()) / blips.length) * TAU);
      }
      paint(canvas, blips, angles.current, colors.current, t);
    },
  });

  return <canvas ref={canvasRef} aria-hidden className="absolute inset-0 size-full" />;
}

function paint(
  canvas: HTMLCanvasElement,
  blips: SonarBlip[],
  angles: number[],
  c: ProofColors,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const cx = w / 2;
  const cy = h / 2 - 6;
  const radius = Math.min(w, h) * 0.42;
  const beam = (t / PERIOD) * TAU - Math.PI / 2;

  ctx.strokeStyle = c.line;
  ctx.lineWidth = 1;
  for (let k = 1; k <= 4; k++) {
    ctx.beginPath();
    ctx.arc(cx, cy, (radius * k) / 4, 0, TAU);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(cx - radius, cy);
  ctx.lineTo(cx + radius, cy);
  ctx.moveTo(cx, cy - radius);
  ctx.lineTo(cx, cy + radius);
  ctx.stroke();

  if ("createConicGradient" in ctx) {
    const sweep = ctx.createConicGradient(beam - 1.1, cx, cy);
    sweep.addColorStop(0, withAlpha(c.brand, 0));
    sweep.addColorStop(0.175, withAlpha(c.brand, 0.28));
    sweep.addColorStop(0.176, withAlpha(c.brand, 0));
    sweep.addColorStop(1, withAlpha(c.brand, 0));
    ctx.fillStyle = sweep;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, TAU);
    ctx.fill();
  }
  ctx.strokeStyle = c.brand;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(beam) * radius, cy + Math.sin(beam) * radius);
  ctx.stroke();
  ctx.lineWidth = 1;

  ctx.font = `500 11px ${MONO_FONT}`;
  ctx.textBaseline = "middle";
  blips.forEach((blip, i) => {
    const angle = angles[i];
    const strength = blip.max > 0 ? blip.score / blip.max : 0;
    const dist = radius * (0.95 - strength * 0.8);
    const bx = cx + Math.cos(angle) * dist;
    const by = cy + Math.sin(angle) * dist;
    const behind = (((beam - angle) % TAU) + TAU * 2) % TAU;
    const since = (behind / TAU) * PERIOD;
    const glow = Math.exp(-since * 1.3);
    if (since < 1.2) {
      ctx.strokeStyle = withAlpha(c.brand, (1 - since / 1.2) * 0.6);
      ctx.beginPath();
      ctx.arc(bx, by, 4 + since * 26, 0, TAU);
      ctx.stroke();
    }
    ctx.fillStyle = withAlpha(c.brand, 0.2 + 0.8 * glow * Math.max(strength, 0.25));
    ctx.beginPath();
    ctx.arc(bx, by, 2.5 + strength * 4, 0, TAU);
    ctx.fill();
    const right = Math.cos(angle) >= 0;
    ctx.textAlign = right ? "left" : "right";
    ctx.fillStyle = withAlpha(c.fg, 0.3 + 0.7 * glow);
    ctx.fillText(`${blip.ticker} ${blip.score}/${blip.max}`, bx + (right ? 9 : -9), by);
  });

  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = c.muted;
  ctx.fillText("Nearer the centre: more rules pass", 12, h - 12);
}
