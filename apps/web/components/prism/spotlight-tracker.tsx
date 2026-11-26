"use client";

/**
 * One document-level pointer listener that feeds every `.spotlight` tile its
 * pointer position (`--mx`, `--my`), so tiles light their border where the
 * pointer is without each wiring its own handler. Fine pointers only.
 */

import { mediaMatches } from "@/lib/media";
import { useEffect } from "react";

export function SpotlightTracker() {
  useEffect(() => {
    if (!mediaMatches("(pointer: fine)")) return;
    let current: HTMLElement | null = null;
    const onMove = (event: PointerEvent) => {
      const tile = (event.target as Element | null)?.closest?.<HTMLElement>(".spotlight") ?? null;
      if (tile !== current) current = tile;
      if (!tile) return;
      const rect = tile.getBoundingClientRect();
      tile.style.setProperty("--mx", `${event.clientX - rect.left}px`);
      tile.style.setProperty("--my", `${event.clientY - rect.top}px`);
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => document.removeEventListener("pointermove", onMove);
  }, []);
  return null;
}
