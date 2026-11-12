"use client";

/**
 * Fog of the future: the replay proof.
 *
 * Stored daily closes draw up to a playhead; everything after it sits under a
 * slow, moving fog, the way Replay hides bars you have not reached. The
 * playhead steps forward a day at a time, stops on a decision ("Your call"),
 * then the fog rolls back to show what came next. The decision chips are part
 * of the picture, not controls: the real choice happens in /replay.
 */

import { useRef } from "react";

import {
  MONO_FONT,
  type ProofColors,
  easeInOut,
  fitCanvas,
  lerp,
  readProofColors,
  seeded,
  span,
  useFrameLoop,
  withAlpha,
} from "@/components/marketing/proofs/canvas-loop";

const PAUSE_START = 5;
const PAUSE_END = 7.4;

export function FogReplay({ closes, dates }: { closes: number[]; dates: string[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const callRef = useRef<HTMLDivElement>(null);
  const colors = useRef<ProofColors | null>(null);
  const blobs = useRef<Blob[] | null>(null);

  useFrameLoop(canvasRef, {
    duration: 12,
    final: 6.6,
    draw: (t) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      colors.current ??= readProofColors();
      blobs.current ??= makeBlobs();
      const call = callRef.current;
      if (call) {
        const on = t >= PAUSE_START && t < PAUSE_END;
        call.style.opacity = on ? "1" : "0";
        call.dataset.pick = t > 6.2 ? "hold" : "";
      }
      paint(canvas, closes, dates, blobs.current, colors.current, t);
    },
  });

  return (
    <div aria-hidden className="absolute inset-0">
      <canvas ref={canvasRef} className="absolute inset-0 size-full" />
      <div
        ref={callRef}
        className="glass group absolute bottom-10 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full py-1.5 pr-1.5 pl-3.5 text-xs whitespace-nowrap opacity-0 transition-opacity duration-300"
      >
        Your call
        {["Buy", "Hold", "Sell"].map((label) => (
          <span
            key={label}
            className={
              label === "Hold"
                ? "rounded-full border border-border px-2.5 py-1 group-data-[pick=hold]:bg-foreground group-data-[pick=hold]:text-background"
                : "rounded-full border border-border px-2.5 py-1"
            }
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

type Blob = { x: number; y: number; r: number; speed: number; phase: number };

function makeBlobs(): Blob[] {
  const random = seeded(300);
  return Array.from({ length: 24 }, () => ({
    x: random(),
    y: random(),
    r: 0.14 + random() * 0.2,
    speed: 0.2 + random() * 0.5,
    phase: random() * 6,
  }));
}

function paint(
  canvas: HTMLCanvasElement,
  closes: number[],
  dates: string[],
  blobs: Blob[],
  c: ProofColors,
  t: number,
) {
  const fit = fitCanvas(canvas);
  if (!fit) return;
  const { ctx, w, h } = fit;
  const n = closes.length;
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const X = (i: number) => 14 + (i / (n - 1)) * (w - 28);
  const Y = (v: number) => 16 + (1 - (v - lo) / (hi - lo || 1)) * (h - 64);
  const pauseAt = Math.round(n * 0.6);
  const day =
    t < PAUSE_START
      ? lerp(Math.round(n * 0.15), pauseAt, span(t, 0.3, PAUSE_START))
      : t < PAUSE_END
        ? pauseAt
        : lerp(pauseAt, n - 1, easeInOut(span(t, PAUSE_END, 10.4)));
  const at = Math.floor(day);

  ctx.strokeStyle = c.line;
  for (let k = 1; k < 4; k++) {
    const y = Math.round(((h - 48) * k) / 4) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  // The whole series, faint: the fog below hides most of what is ahead.
  ctx.globalAlpha = 0.2;
  ctx.strokeStyle = c.fg;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  closes.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
  ctx.stroke();
  ctx.globalAlpha = 1;

  const area = ctx.createLinearGradient(0, 0, 0, h);
  area.addColorStop(0, withAlpha(c.brand, 0.27));
  area.addColorStop(1, withAlpha(c.brand, 0));
  ctx.fillStyle = area;
  ctx.beginPath();
  for (let i = 0; i <= at; i++) ctx.lineTo(X(i), Y(closes[i]));
  ctx.lineTo(X(at), h);
  ctx.lineTo(X(0), h);
  ctx.fill();
  ctx.strokeStyle = c.brand;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= at; i++) {
    if (i === 0) ctx.moveTo(X(i), Y(closes[i]));
    else ctx.lineTo(X(i), Y(closes[i]));
  }
  ctx.stroke();

  const px = X(day);
  const edge = ctx.createLinearGradient(px - 6, 0, px + 70, 0);
  edge.addColorStop(0, withAlpha(c.card, 0));
  edge.addColorStop(1, withAlpha(c.card, 0.94));
  ctx.fillStyle = edge;
  ctx.fillRect(px - 6, 0, w, h);
  ctx.save();
  ctx.beginPath();
  ctx.rect(px + 10, 0, w, h);
  ctx.clip();
  for (const b of blobs) {
    const bx = px + 30 + ((b.x * w + t * b.speed * 30) % w);
    const by = b.y * h + Math.sin(t * b.speed + b.phase) * 12;
    const br = b.r * h * 1.3;
    const fog = ctx.createRadialGradient(bx, by, 0, bx, by, br);
    fog.addColorStop(0, withAlpha(c.muted, 0.22));
    fog.addColorStop(1, withAlpha(c.muted, 0));
    ctx.fillStyle = fog;
    ctx.beginPath();
    ctx.arc(bx, by, br, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  ctx.strokeStyle = c.fg;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(Math.round(px) + 0.5, 8);
  ctx.lineTo(Math.round(px) + 0.5, h - 44);
  ctx.stroke();
  ctx.fillStyle = c.fg;
  ctx.beginPath();
  ctx.arc(px, Y(closes[at]), 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.font = `500 12px ${MONO_FONT}`;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillStyle = c.fg;
  ctx.fillText(dates[at] ?? "", 14, h - 12);
  ctx.textAlign = "right";
  ctx.fillStyle = c.muted;
  ctx.fillText(`Bar ${at + 1} of ${n}`, w - 14, h - 12);
}
