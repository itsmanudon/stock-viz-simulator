"use client";

import { Keyboard, MonitorCog, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";

import {
  DENSITY_STORAGE_KEY,
  type InterfaceDensity,
  applyInterfaceDensity,
} from "@/components/interface-preferences";

export function SettingsWorkspace({
  email,
  name,
}: {
  email: string | null | undefined;
  name: string | null | undefined;
}) {
  const [density, setDensity] = useState<InterfaceDensity>("comfortable");

  useEffect(() => {
    const next: InterfaceDensity =
      window.localStorage.getItem(DENSITY_STORAGE_KEY) === "compact" ? "compact" : "comfortable";
    setDensity(next);
    applyInterfaceDensity(next);
  }, []);

  function updateDensity(next: InterfaceDensity) {
    setDensity(next);
    window.localStorage.setItem(DENSITY_STORAGE_KEY, next);
    applyInterfaceDensity(next);
  }

  return (
    <div className="space-y-4">
      <section
        className="rounded-xl border border-border-muted bg-surface-secondary/45 p-4"
        aria-labelledby="account-heading"
      >
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-brand/30 bg-brand/10 text-sm font-semibold text-brand">
            {(name || email || "S").slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h2 id="account-heading" className="text-sm font-semibold">
              {name || "StockViz account"}
            </h2>
            <p className="mt-0.5 truncate text-xs text-text-tertiary">
              {email || "Signed-in account"}
            </p>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-text-secondary">
          Your account is used for paper-trading data, watchlists, alerts, and private preferences.
          StockViz never routes orders to a live broker.
        </p>
      </section>

      <section
        className="rounded-xl border border-border-muted bg-surface-secondary/45 p-4"
        aria-labelledby="interface-heading"
      >
        <div className="flex items-start gap-3">
          <MonitorCog className="mt-0.5 size-4 text-brand" aria-hidden />
          <div className="min-w-0 flex-1">
            <h2 id="interface-heading" className="text-sm font-semibold">
              Interface
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-text-tertiary">
              Choose how dense data tables and workspace spacing feel on this device.
            </p>
            <fieldset className="mt-3 grid grid-cols-2 gap-2">
              <legend className="sr-only">Interface density</legend>
              {(["comfortable", "compact"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={density === option}
                  onClick={() => updateDensity(option)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                    density === option
                      ? "border-brand/60 bg-brand/10 text-brand"
                      : "border-border-muted text-text-secondary hover:bg-surface-hover"
                  }`}
                >
                  <span className="block font-medium capitalize">{option}</span>
                  <span className="mt-0.5 block text-2xs text-text-tertiary">
                    {option === "compact" ? "More rows in view" : "More breathing room"}
                  </span>
                </button>
              ))}
            </fieldset>
            <p className="mt-2 text-2xs text-text-tertiary">Saved locally in this browser.</p>
          </div>
        </div>
      </section>

      <ShortcutsDialog />
    </div>
  );
}

function ShortcutsDialog() {
  const shortcuts = [
    ["⌘ K / Ctrl K", "Open symbol command palette"],
    ["/", "Open the palette when you are not typing"],
    ["↑ ↓", "Move through symbol results"],
    ["Enter", "Open the selected symbol workspace"],
    ["Esc", "Close the active surface"],
  ];

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="inline-flex w-full items-center justify-between rounded-lg border border-border-muted px-3 py-2.5 text-left text-xs text-text-secondary transition hover:bg-surface-hover hover:text-foreground"
        >
          <span className="inline-flex items-center gap-2">
            <Keyboard className="size-4 text-brand" aria-hidden /> Keyboard shortcuts
          </span>
          <span className="font-mono text-2xs text-text-tertiary">⌘ K</span>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-surface-elevated p-5 shadow-2xl outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-base font-semibold">Keyboard shortcuts</Dialog.Title>
              <Dialog.Description className="mt-1 text-xs text-text-tertiary">
                Quick ways to move through StockViz.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="inline-flex size-8 items-center justify-center rounded-md text-text-tertiary hover:bg-surface-hover hover:text-foreground"
                aria-label="Close shortcuts"
              >
                <X className="size-4" aria-hidden />
              </button>
            </Dialog.Close>
          </div>
          <div className="mt-5 divide-y divide-border-muted rounded-lg border border-border-muted">
            {shortcuts.map(([key, description]) => (
              <div
                key={key}
                className="flex items-center justify-between gap-4 px-3 py-2.5 text-xs"
              >
                <span className="text-text-secondary">{description}</span>
                <kbd className="shrink-0 rounded border border-border-muted bg-surface-secondary px-2 py-1 font-mono text-2xs text-foreground">
                  {key}
                </kbd>
              </div>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
