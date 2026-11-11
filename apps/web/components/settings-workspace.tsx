"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import {
  DENSITY_STORAGE_KEY,
  type InterfaceDensity,
  applyInterfaceDensity,
} from "@/components/interface-preferences";
import { cn } from "@/lib/utils";

/**
 * The Settings page's client panels (Aurora board v3): interface preferences
 * in the main column, and the account card and keyboard shortcuts in the
 * aside. Everything here lives in this browser; account preferences that the
 * API stores (currency, leaderboard) stay server actions on the page.
 */

const DENSITY_OPTIONS = [
  { value: "comfortable", label: "Comfortable", hint: "More breathing room" },
  { value: "compact", label: "Compact", hint: "More rows in view" },
] as const;

/** Light and dark only: the theme provider runs with `enableSystem={false}`. */
const THEME_OPTIONS = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
] as const;

export function InterfacePanel() {
  const [density, setDensity] = useState<InterfaceDensity>("comfortable");
  const { theme, setTheme } = useTheme();
  // next-themes only knows the theme after mount; rendering a pressed state
  // before that would mismatch the server HTML.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const next: InterfaceDensity =
      window.localStorage.getItem(DENSITY_STORAGE_KEY) === "compact" ? "compact" : "comfortable";
    setDensity(next);
    applyInterfaceDensity(next);
    setMounted(true);
  }, []);

  function updateDensity(next: InterfaceDensity) {
    setDensity(next);
    window.localStorage.setItem(DENSITY_STORAGE_KEY, next);
    applyInterfaceDensity(next);
  }

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-xs text-text-tertiary">Density</legend>
        <div className="grid max-w-md grid-cols-2 gap-2">
          {DENSITY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={density === option.value}
              onClick={() => updateDensity(option.value)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left text-xs transition",
                density === option.value
                  ? "border-brand/60 bg-brand/10 text-foreground"
                  : "border-border-muted text-text-secondary hover:bg-surface-hover",
              )}
            >
              <span className="block font-medium">{option.label}</span>
              <span className="mt-0.5 block text-2xs text-text-tertiary">{option.hint}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-xs text-text-tertiary">Theme</legend>
        <div className="inline-flex gap-0.5 rounded-full border border-border-muted p-0.5">
          {THEME_OPTIONS.map((option) => {
            const pressed = mounted && theme === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={pressed}
                onClick={() => setTheme(option.value)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs transition",
                  pressed
                    ? "bg-surface-secondary font-medium text-foreground"
                    : "text-text-tertiary hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </fieldset>

      <p className="text-2xs text-text-tertiary">
        Density and theme are saved in this browser only.
      </p>
    </div>
  );
}

export function AccountDetails({
  email,
  name,
}: {
  email: string | null | undefined;
  name: string | null | undefined;
}) {
  return (
    <div>
      <dl className="divide-y divide-border-muted text-sm">
        <div className="flex justify-between gap-3 py-2">
          <dt className="text-text-tertiary">Name</dt>
          <dd className="min-w-0 truncate text-right">{name || "StockViz account"}</dd>
        </div>
        <div className="flex justify-between gap-3 py-2">
          <dt className="text-text-tertiary">Email</dt>
          <dd className="min-w-0 truncate text-right">{email || "Signed-in account"}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-text-secondary">
        Your account holds paper-trading data, watchlists, alerts and private preferences. StockViz
        never routes orders to a live broker.
      </p>
    </div>
  );
}

const SHORTCUTS = [
  ["⌘ K / Ctrl K", "Open the symbol palette"],
  ["/", "Open it when not typing"],
  ["↑ ↓", "Move through results"],
  ["Enter", "Open the selected symbol"],
  ["Esc", "Close the active surface"],
] as const;

/** The shortcut list, shown inline rather than behind a dialog. */
export function KeyboardShortcuts() {
  return (
    <dl className="divide-y divide-border-muted text-xs">
      {SHORTCUTS.map(([key, description]) => (
        <div key={key} className="flex items-center justify-between gap-4 py-2">
          <dt className="text-text-secondary">{description}</dt>
          <dd>
            <kbd className="rounded border border-border-muted bg-surface-secondary px-2 py-0.5 font-mono text-2xs text-foreground">
              {key}
            </kbd>
          </dd>
        </div>
      ))}
    </dl>
  );
}
