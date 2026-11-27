"use client";

/**
 * The chart toolbar's volume profile switch (A6.7, M2.9): Off, Visible range
 * or Fixed range. The choice is URL state (`?vp=`), written in the browser
 * only (`history.replaceState`), so the server never re-renders for it; the
 * chart's tools (`chart-tools.tsx`) read it with `useSearchParams`. Other
 * toolbar links leave it out, so a new interval starts with it off.
 *
 * An index's stored volume is 0, not real, so it is offered no profile: the
 * switch is shown disabled with the reason.
 */

import { usePathname, useSearchParams } from "next/navigation";

import {
  PROFILE_MODES,
  PROFILE_PARAM,
  type ProfileMode,
  parseProfileMode,
} from "@/lib/volume-profile";

export const INDEX_NO_PROFILE =
  "No volume profile: an index's stored volume is 0, not real volume.";

export function profileHref(pathname: string, search: string, mode: ProfileMode): string {
  const params = new URLSearchParams(search);
  if (mode === "off") params.delete(PROFILE_PARAM);
  else params.set(PROFILE_PARAM, mode);
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

export function VolumeProfileToggle({ offered }: { offered: boolean }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const mode = parseProfileMode(search.get(PROFILE_PARAM));
  return (
    <fieldset
      className="flex items-center gap-1 rounded-md border border-border-muted p-0.5"
      data-testid="volume-profile-toggle"
      data-mode={mode}
    >
      <legend className="sr-only">Volume profile</legend>
      <span className="px-1 text-2xs text-text-tertiary" aria-hidden>
        Profile
      </span>
      {PROFILE_MODES.map((option) => {
        const active = mode === option.value;
        const disabled = !offered && option.value !== "off";
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            aria-disabled={disabled || undefined}
            title={disabled ? INDEX_NO_PROFILE : undefined}
            aria-label={`Volume profile: ${option.label}${disabled ? `. ${INDEX_NO_PROFILE}` : ""}`}
            data-mode={option.value}
            onClick={() => {
              if (disabled) return;
              window.history.replaceState(
                null,
                "",
                profileHref(pathname, search.toString(), option.value),
              );
            }}
            className={`inline-flex h-7 items-center justify-center rounded-sm px-2 text-xs font-medium transition-colors ${
              active
                ? "bg-brand/12 text-brand"
                : disabled
                  ? "cursor-not-allowed text-text-tertiary opacity-60"
                  : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
            }`}
          >
            {option.value === "off" ? "Off" : option.value === "visible" ? "Visible" : "Fixed"}
          </button>
        );
      })}
    </fieldset>
  );
}
