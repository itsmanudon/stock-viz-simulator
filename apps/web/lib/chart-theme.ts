"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

/**
 * Bridge between the CSS design tokens and the canvas charts.
 *
 * lightweight-charts paints to a canvas, so it can't consume `var(--positive)`
 * the way the rest of the UI does — it needs concrete colour strings. Reading
 * the tokens off the document at runtime keeps one source of truth: change a
 * token in globals.css and the charts follow, in both themes.
 */
export type ChartPalette = {
  positive: string;
  negative: string;
  /** Semi-transparent variants for volume bars and area fills. */
  positiveFill: string;
  negativeFill: string;
  text: string;
  grid: string;
  axis: string;
  /** A3.1: the line and area chart types' stroke, and the area's fill stops. */
  line: string;
  areaTop: string;
  areaBottom: string;
  /** Categorical colours for indicator overlays, in assignment order. */
  overlays: readonly string[];
};

const FALLBACK: ChartPalette = {
  positive: "#147a56",
  negative: "#c93c45",
  positiveFill: "rgba(20, 122, 86, 0.4)",
  negativeFill: "rgba(201, 60, 69, 0.4)",
  text: "#808080",
  grid: "rgba(222, 222, 222, 0.9)",
  axis: "#dedede",
  line: "#0b1220",
  areaTop: "rgba(11, 18, 32, 0.18)",
  areaBottom: "rgba(11, 18, 32, 0)",
  /* Categorical ramp deliberately excludes the blue brand and P&L colors so
     an overlay is never mistaken for an action or a gain. */
  overlays: ["#8277e8", "#4baebd", "#d36f9b", "#e59152", "#6287b9"],
};

function readToken(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  return styles.getPropertyValue(name).trim() || fallback;
}

/** `#rrggbb` -> `rgba(r, g, b, alpha)`; passes non-hex values through. */
function withAlpha(color: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (!match) return color;
  const int = Number.parseInt(match[1], 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function readPalette(): ChartPalette {
  if (typeof window === "undefined") return FALLBACK;

  const styles = getComputedStyle(document.documentElement);
  const positive = readToken(styles, "--positive", FALLBACK.positive);
  const negative = readToken(styles, "--negative", FALLBACK.negative);
  const border = readToken(styles, "--border-muted", FALLBACK.axis);
  const line = readToken(styles, "--foreground", FALLBACK.line);

  return {
    positive,
    negative,
    positiveFill: withAlpha(positive, 0.4),
    negativeFill: withAlpha(negative, 0.4),
    text: readToken(styles, "--text-tertiary", FALLBACK.text),
    grid: withAlpha(border, 0.9),
    axis: border,
    line,
    areaTop: withAlpha(line, 0.18),
    areaBottom: withAlpha(line, 0),
    overlays: FALLBACK.overlays,
  };
}

function sameColors(a: ChartPalette, b: ChartPalette): boolean {
  return (
    a.positive === b.positive &&
    a.negative === b.negative &&
    a.text === b.text &&
    a.grid === b.grid &&
    a.axis === b.axis &&
    a.line === b.line
  );
}

/**
 * Resolved chart palette for the active theme.
 *
 * Returns the light-mode fallback on the server and for the first client
 * render, then re-reads once `next-themes` has resolved and applied `.dark`.
 *
 * The returned object's identity is stable while the colours are unchanged.
 * That matters: callers put this in a `useEffect` dependency array, and
 * lightweight-charts has no way to restyle in place — a new identity means
 * `chart.remove()` plus a full rebuild. Handing back a fresh object on every
 * render would tear the charts down repeatedly and leave unpainted canvases
 * behind.
 */
export function useChartPalette(): ChartPalette {
  const { resolvedTheme } = useTheme();
  const [palette, setPalette] = useState<ChartPalette>(FALLBACK);

  // biome-ignore lint/correctness/useExhaustiveDependencies: resolvedTheme is the trigger for re-reading the DOM, not a value read here.
  useEffect(() => {
    setPalette((current) => {
      const next = readPalette();
      return sameColors(current, next) ? current : next;
    });
  }, [resolvedTheme]);

  return palette;
}
