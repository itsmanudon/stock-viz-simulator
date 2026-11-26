"use client";

import { cn } from "@/lib/utils";

import { useSound } from "./sound-provider";

/**
 * The sound switch. A real `role="switch"` with a visible state: four bars
 * that dance while sound is on (still under reduced motion) and lie flat
 * when it is off. The label says what pressing it does.
 */
export function SoundToggle({
  className,
  showLabel = false,
}: { className?: string; showLabel?: boolean }) {
  const { enabled, setEnabled } = useSound();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label="Interface sound"
      title={enabled ? "Sound on. Press to mute." : "Sound off. Press to turn on."}
      data-sound="none"
      onClick={() => setEnabled(!enabled)}
      className={cn(
        "group inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-border-muted px-3 text-xs text-text-secondary transition-colors hover:border-border hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
        enabled && "border-brand/40 text-foreground",
        className,
      )}
    >
      <span aria-hidden className="sound-bars" data-on={enabled ? "true" : undefined}>
        <i />
        <i />
        <i />
        <i />
      </span>
      {showLabel ? (
        <span className="font-mono text-3xs tracking-[0.02em]">
          {enabled ? "Sound On" : "Sound Off"}
        </span>
      ) : null}
    </button>
  );
}
