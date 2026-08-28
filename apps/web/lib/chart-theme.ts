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
  /** Categorical colours for indicator overlays, in assignment order. */
  overlays: readonly string[];
};

const FALLBACK: ChartPalette = {
  positive: "#137558",
  negative: "#b94343",
  positiveFill: "rgba(19, 117, 88, 0.4)",
  negativeFill: "rgba(185, 67, 67, 0.4)",
  text: "#89857b",
  grid: "rgba(229, 225, 216, 0.9)",
  axis: "#e5e1d8",
  /* Categorical ramp deliberately excludes gold and the P&L green/red so an
     overlay is never mistaken for the brand or a gain. */
  overlays: ["#7669c4", "#267d8a", "#a45f7a", "#b87935", "#4e779f"],
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

  return {
    positive,
    negative,
    positiveFill: withAlpha(positive, 0.4),
    negativeFill: withAlpha(negative, 0.4),
    text: readToken(styles, "--text-tertiary", FALLBACK.text),
    grid: withAlpha(border, 0.9),
    axis: border,
    overlays: FALLBACK.overlays,
  };
}

function sameColors(a: ChartPalette, b: ChartPalette): boolean {
  return (
    a.positive === b.positive &&
    a.negative === b.negative &&
    a.text === b.text &&
    a.grid === b.grid &&
    a.axis === b.axis
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
