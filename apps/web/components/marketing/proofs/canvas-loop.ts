"use client";

/**
 * The frame loop behind the landing "Watch it work" animations.
 *
 * Every animation is a pure function of time: `draw(t)` paints the frame for
 * `t` seconds into the loop, so a frame never depends on the one before it.
 * That keeps the loop simple to pause and restart:
 *
 * - It runs only while the element is on screen, and restarts from zero each
 *   time it comes back into view, so a visitor always sees the beginning.
 * - With reduced motion it paints the `final` frame once (and again on
 *   resize) and never animates. The final frame carries every figure.
 * - Before it starts, and without JavaScript, the section's text still states
 *   the same figures, so nothing is gated behind the animation.
 *
 * No GSAP here: these are canvas and inline-style redraws, which a timeline
 * would add nothing to.
 */

import { type RefObject, useEffect, useRef } from "react";

export type Frame = (t: number, raw: number) => void;

export function useFrameLoop(
  target: RefObject<Element | null>,
  { duration, final, draw }: { duration: number; final: number; draw: Frame },
) {
  // The latest draw function, so a parent re-render never restarts the loop.
  const drawRef = useRef(draw);
  drawRef.current = draw;

  useEffect(() => {
    const el = target.current;
    if (!el) return;
    const paintFinal = () => drawRef.current(final, final);
    paintFinal();

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduced.matches) {
      const onResize = () => paintFinal();
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }

    let frame = 0;
    let start = 0;
    let visible = false;
    const tick = (now: number) => {
      const raw = (now - start) / 1000;
      drawRef.current(raw % duration, raw);
      frame = requestAnimationFrame(tick);
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !visible) {
          visible = true;
          start = performance.now();
          frame = requestAnimationFrame(tick);
        } else if (!entry.isIntersecting && visible) {
          visible = false;
          cancelAnimationFrame(frame);
          paintFinal();
        }
      },
      { rootMargin: "40px" },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [target, duration, final]);
}

/** Size a canvas to its box at the device pixel ratio and clear it. */
export function fitCanvas(canvas: HTMLCanvasElement) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

/** Colours for canvas drawing, read once from the theme tokens. */
export type ProofColors = {
  fg: string;
  muted: string;
  line: string;
  brand: string;
  brandFrom: string;
  pos: string;
  neg: string;
  card: string;
};

export function readProofColors(): ProofColors {
  const s = getComputedStyle(document.documentElement);
  const get = (name: string, fallback: string) => s.getPropertyValue(name).trim() || fallback;
  return {
    fg: get("--foreground", "#eef2f8"),
    muted: get("--text-tertiary", "#8892a4"),
    line: get("--border-muted", "#182030"),
    brand: get("--brand-gradient-via", "#38c8f0"),
    brandFrom: get("--brand-gradient-from", "#4255ff"),
    pos: get("--positive", "#3dd68c"),
    neg: get("--negative", "#ff6b78"),
    card: get("--card", "#0b101b"),
  };
}

/** A token colour at the given opacity. Tokens are six-digit hex. */
export function withAlpha(color: string, alpha: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return color;
  return `${color}${Math.round(alpha * 255)
    .toString(16)
    .padStart(2, "0")}`;
}

export const MONO_FONT = '"Geist Mono", ui-monospace, Menlo, monospace';

export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
/** Progress of `t` through the span `a`..`b`, clamped to 0..1. */
export const span = (t: number, a: number, b: number) => clamp((t - a) / (b - a), 0, 1);
export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
export const easeOut = (t: number) => 1 - (1 - t) ** 3;
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Deterministic random numbers, so every visitor sees the same picture. */
export function seeded(seed: number) {
  let s = seed;
  return () => {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
