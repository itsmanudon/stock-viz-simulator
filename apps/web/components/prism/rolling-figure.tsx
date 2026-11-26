"use client";

/**
 * A figure whose digits roll into place like an odometer when it first
 * appears (NumberFlow-style).
 *
 * The figure is plain text on the server, without JavaScript, with reduced
 * motion, and again as soon as the roll ends, so copying it, reading it with
 * assistive technology or matching it in a test always sees the real value.
 * Only during the roll (about a second) is it drawn as digit columns, with
 * the real text kept in a visually-hidden copy.
 */

import { useEffect, useRef, useState } from "react";

import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
const ROLL_MS = 1300;

export function RollingFigure({ text, className }: { text: string; className?: string }) {
  const [rolling, setRolling] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  // Start a roll on mount and whenever the figure changes.
  useEffect(() => {
    if (!text || !mediaMatches("(prefers-reduced-motion: no-preference)")) return;
    setRolling(true);
    const done = window.setTimeout(() => setRolling(false), ROLL_MS + text.length * 40);
    return () => window.clearTimeout(done);
  }, [text]);

  // Once the columns are on screen at zero, send each to its digit.
  useEffect(() => {
    if (!rolling) return;
    const el = ref.current;
    if (!el) return;
    const columns = [...el.querySelectorAll<HTMLElement>("[data-roll]")];
    const frame = requestAnimationFrame(() => {
      columns.forEach((col, i) => {
        col.style.transition = `transform ${800 + i * 60}ms cubic-bezier(0.16, 1, 0.3, 1) ${i * 25}ms`;
        col.style.transform = `translateY(-${Number(col.dataset.roll) * 10}%)`;
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [rolling]);

  if (!rolling) return <span className={className}>{text}</span>;

  return (
    <span className={cn("relative inline-block", className)}>
      <span className="sr-only">{text}</span>
      <span ref={ref} aria-hidden className="inline-flex tabular-nums">
        {[...text].map((ch, i) => {
          const digit = DIGITS.indexOf(ch);
          if (digit < 0) {
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: characters of a fixed string
              <span key={i} className="inline-block whitespace-pre">
                {ch}
              </span>
            );
          }
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: characters of a fixed string
            <span key={i} className="relative inline-block h-[1.15em] overflow-hidden align-bottom">
              <span className="invisible block h-[1.15em] leading-[1.15em]">0</span>
              <span data-roll={digit} className="absolute inset-x-0 top-0 flex flex-col">
                {DIGITS.map((d) => (
                  <span key={d} className="block h-[1.15em] leading-[1.15em]">
                    {d}
                  </span>
                ))}
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
