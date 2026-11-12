"use client";

/**
 * Decode tape: a figure scrambles through digits and resolves left to right
 * when it comes into view, like a terminal tape printing the latest close.
 *
 * The real text is always in the DOM for assistive technology (sr-only), and
 * the server renders the resolved figure, so nothing depends on the effect.
 * Symbols and separators ($, ₹, commas, the point, %, arrows) never scramble,
 * only digits do, so the shape of the number holds still while it resolves.
 */

import { useRef } from "react";

import { useFrameLoop } from "@/components/marketing/proofs/canvas-loop";

const DIGITS = "0123456789";
const STEP = 0.055;

export function DecodeText({ text, delay = 0 }: { text: string; delay?: number }) {
  const ref = useRef<HTMLSpanElement>(null);

  useFrameLoop(ref, {
    // Long enough to play once per visit; it restarts when scrolled back in.
    duration: 600,
    final: 600,
    draw: (t) => {
      const el = ref.current;
      if (!el) return;
      let out = "";
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        const at = 0.15 + delay + i * STEP;
        out += t >= at || !/\d/.test(ch) ? ch : DIGITS[(Math.floor(t * 22) + i * 3) % 10];
      }
      if (el.textContent !== out) el.textContent = out;
    },
  });

  return (
    <>
      <span className="sr-only">{text}</span>
      <span ref={ref} aria-hidden className="tabular-nums">
        {text}
      </span>
    </>
  );
}
