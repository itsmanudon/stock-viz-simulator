"use client";

import { useEffect } from "react";

export const DENSITY_STORAGE_KEY = "stockviz.settings.density";
export type InterfaceDensity = "comfortable" | "compact";

export function applyInterfaceDensity(density: InterfaceDensity) {
  document.documentElement.dataset.density = density;
}

export function InterfacePreferences({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const stored = window.localStorage.getItem(DENSITY_STORAGE_KEY);
    applyInterfaceDensity(stored === "compact" ? "compact" : "comfortable");
  }, []);

  return children;
}
