"use client";

/**
 * "Everything in the workspace" as six stops on a terrain (owner, 28 Nov
 * 2026, mockup 4): ridge lines that flow like waves, six numbered pins that
 * ride them, and a panel for the stop in view.
 *
 * - Pins and the arrows choose a stop; the view eases toward it (the
 *   "camera"), and the panel names the surface, says what it does today
 *   and links to it. "Stop N of 6" sits above the stage only.
 * - The waves run on one rAF loop that writes path data and pin offsets
 *   straight to the DOM (no React render per frame), only while the section
 *   is on screen. Reduced motion: still ridges, no easing.
 * - The terrain is decoration (aria-hidden); every word is in the panel.
 */

import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

type Stop = {
  label: string;
  href: string;
  lead: string;
  detail: string;
  /** Where the pin stands: across (0 to 1) and which ridge it rides. */
  x: number;
  ridge: number;
};

export const STOPS: Stop[] = [
  {
    label: "Markets",
    href: "/markets",
    lead: "Every tracked symbol.",
    detail: "Latest stored close and daily change, sortable.",
    x: 0.17,
    ridge: 9,
  },
  {
    label: "Screener",
    href: "/screener",
    lead: "Narrow the universe.",
    detail: "Filter tracked symbols by the metrics you care about.",
    x: 0.33,
    ridge: 5,
  },
  {
    label: "Checklist",
    href: "/checklist",
    lead: "Six published conditions.",
    detail: "Each with its formula and evidence grade, per symbol. Not investment advice.",
    x: 0.47,
    ridge: 11,
  },
  {
    label: "Backtest",
    href: "/backtest",
    lead: "Test before you trade.",
    detail: "Run a strategy over stored daily history and read the equity curve.",
    x: 0.6,
    ridge: 4,
  },
  {
    label: "Paper trading",
    href: "/trade",
    lead: "$100,000 to practise with.",
    detail: "Market and limit orders, filled at stored daily closes.",
    x: 0.72,
    ridge: 10,
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    lead: "Keep score.",
    detail: "Positions, value history, dividends and a trading journal.",
    x: 0.84,
    ridge: 6,
  },
];

const W = 1000;
const H = 520;
const RIDGES = 14;
const SAMPLES = 64;

/** Height of ridge `r` at `x` (0 to 1) and time `t` seconds, in viewBox units. */
function ridgeY(r: number, x: number, t: number): number {
  const depth = r / (RIDGES - 1); // 0 = far, 1 = near
  const base = 70 + depth * (H - 110);
  const amp = 6 + depth * 34;
  const wave =
    Math.sin(x * 7.5 + t * 0.9 + r * 0.55) * 0.6 +
    Math.sin(x * 15 - t * 0.6 + r * 1.3) * 0.25 +
    Math.sin(x * 3.2 + t * 0.35) * 0.4;
  return base + wave * amp;
}

function ridgePath(r: number, t: number): string {
  let d = "";
  for (let i = 0; i <= SAMPLES; i++) {
    const x = i / SAMPLES;
    d += `${i ? "L" : "M"}${(x * W).toFixed(1)} ${ridgeY(r, x, t).toFixed(1)}`;
  }
  return d;
}

export function WorkspaceStops() {
  const [active, setActive] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const pathRefs = useRef<(SVGPathElement | null)[]>([]);
  const pinRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const stop = STOPS[active];

  // The waves: one loop, on screen only; one still frame with reduced motion.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const draw = (t: number) => {
      pathRefs.current.forEach((path, r) => path?.setAttribute("d", ridgePath(r, t)));
      pinRefs.current.forEach((pin, i) => {
        if (!pin) return;
        const s = STOPS[i];
        pin.style.top = `${(ridgeY(s.ridge, s.x, t) / H) * 100}%`;
      });
    };
    draw(0);
    if (
      mediaMatches("(prefers-reduced-motion: reduce)") ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    let frame = 0;
    let visible = false;
    const t0 = performance.now();
    const loop = (now: number) => {
      draw((now - t0) / 1000);
      frame = requestAnimationFrame(loop);
    };
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !visible) {
        visible = true;
        frame = requestAnimationFrame(loop);
      } else if (!entry.isIntersecting && visible) {
        visible = false;
        cancelAnimationFrame(frame);
      }
    });
    io.observe(stage);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  const go = (delta: number) => setActive((a) => (a + delta + STOPS.length) % STOPS.length);

  return (
    <div className="mt-8 grid gap-6">
      <p className="text-sm text-text-tertiary tabular-nums" aria-live="polite">
        Stop {active + 1} of {STOPS.length}
      </p>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div
          ref={stageRef}
          className="relative h-72 min-w-0 overflow-hidden rounded-3xl sm:aspect-[1000/520] sm:h-auto sm:min-h-72 border border-border-muted bg-[radial-gradient(120%_90%_at_50%_100%,var(--surface-secondary),var(--background))]"
        >
          {/* The camera: the whole terrain eases toward the stop in view. */}
          <div
            className="absolute inset-0 transition-transform duration-1000 ease-out motion-reduce:transition-none"
            style={{ transform: `translateX(${((0.5 - stop.x) * 10).toFixed(2)}%) scale(1.06)` }}
          >
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              aria-hidden="true"
              className="absolute inset-0 size-full"
            >
              {Array.from({ length: RIDGES }, (_, r) => (
                <path
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed ridge slots
                  key={r}
                  ref={(el) => {
                    pathRefs.current[r] = el;
                  }}
                  fill="none"
                  strokeLinecap="round"
                  stroke={r > RIDGES * 0.55 ? "var(--brand)" : "var(--text-tertiary)"}
                  strokeOpacity={0.15 + (r / RIDGES) * 0.55}
                  strokeWidth={0.8 + (r / RIDGES) * 1.2}
                />
              ))}
            </svg>
            {STOPS.map((s, i) => {
              const on = i === active;
              return (
                <button
                  key={s.href}
                  type="button"
                  ref={(el) => {
                    pinRefs.current[i] = el;
                  }}
                  onClick={() => setActive(i)}
                  aria-pressed={on}
                  aria-label={`Stop ${i + 1}: ${s.label}`}
                  className="group absolute flex -translate-x-1/2 -translate-y-full flex-col items-center focus-visible:outline-none"
                  style={{ left: `${s.x * 100}%` }}
                >
                  <span
                    className={cn(
                      "flex items-center gap-2 rounded-full border p-1 backdrop-blur-md sm:pr-3 transition-colors group-focus-visible:ring-2 group-focus-visible:ring-ring",
                      on
                        ? "border-brand/60 bg-brand/15"
                        : "border-border-muted bg-background/70 hover:border-border",
                    )}
                  >
                    <span
                      className={cn(
                        "grid size-7 place-items-center rounded-full text-sm tabular-nums transition-transform group-hover:scale-110",
                        on
                          ? "bg-brand text-background"
                          : "bg-surface-secondary text-text-secondary",
                      )}
                    >
                      {i + 1}
                    </span>
                    <span className="hidden text-sm whitespace-nowrap text-foreground sm:inline">
                      {s.label}
                    </span>
                  </span>
                  <span aria-hidden className="h-8 w-px bg-linear-to-b from-brand to-transparent" />
                </button>
              );
            })}
          </div>
        </div>

        <div
          aria-live="polite"
          className="flex flex-col gap-4 rounded-3xl border border-border-muted bg-card/70 p-6 sm:p-8"
        >
          <p className="text-3xl font-medium tracking-[-0.03em]">{stop.label}</p>
          <p className="text-prism text-2xl font-medium tracking-[-0.02em]">{stop.lead}</p>
          <p className="text-base leading-7 text-text-secondary">{stop.detail}</p>
          <div className="mt-auto flex items-center justify-between gap-3 pt-4">
            <Link
              href={stop.href}
              className="inline-flex items-center gap-1.5 text-base font-medium text-foreground hover:text-brand"
            >
              Open {stop.label}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => go(-1)}
                aria-label="Previous stop"
                className="grid size-11 place-items-center rounded-full border border-border-muted transition-colors hover:border-border focus-visible:outline-2 focus-visible:outline-ring"
              >
                <ChevronLeft className="size-4" aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => go(1)}
                aria-label="Next stop"
                className="grid size-11 place-items-center rounded-full bg-primary text-primary-foreground focus-visible:outline-2 focus-visible:outline-ring"
              >
                <ChevronRight className="size-4" aria-hidden />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
