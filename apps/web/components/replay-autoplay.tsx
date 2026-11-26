"use client";

/**
 * A6.9 (M9.4): autoplay on the replay page. Play, pause and step at 1, 2, 5
 * or 10 bars a second, driven by this client calling `advance`.
 *
 * - **One step at a time.** The next step starts only after the previous one
 *   has answered, and it sends the bar that answer named
 *   (`expected_current_at`). A step that arrives late or twice changes
 *   nothing on the API, so autoplay never moves two bars for one step.
 * - **Speed is a ceiling.** A step starts at most every 1000/speed ms; a slow
 *   answer slows the player down, it never makes it catch up with a burst.
 * - **The API's per-user advance limit** (429) pauses for its retry delay
 *   and then carries on; any other error stops the player and says why.
 * - **It stops on the last bar.** Finishing the session stays a deliberate
 *   click ("Finish replay").
 * - **Keyboard** (outside text fields): space plays or pauses, → steps one
 *   bar, ← pauses, ↑ and ↓ change the speed, 1-4 pick 1, 2, 5 or 10 bars a
 *   second.
 *
 * The page is refreshed after each step (a transition, so a newer refresh
 * replaces an older one) to draw the new bar.
 */

import { Pause, Play, StepForward } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { type AutoplayStep, autoplayStepAction } from "@/app/(product)/(authed)/replay/actions";
import { Button } from "@/components/ui/button";
import {
  AUTOPLAY_SPEEDS,
  type AutoplaySpeed,
  autoplayDelayMs,
  speedForKey,
  stepSpeed,
} from "@/lib/replay";
import { cn } from "@/lib/utils";

type StepFn = (sessionId: number, currentAt: string) => Promise<AutoplayStep>;

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function ReplayAutoplay({
  sessionId,
  currentAt,
  hasNext,
  step,
  now = () => performance.now(),
}: {
  sessionId: number;
  currentAt: string;
  hasNext: boolean;
  /** For tests: the step call (default the server action). */
  step?: StepFn;
  now?: () => number;
}) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<AutoplaySpeed>(1);
  const [advances, setAdvances] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [atEnd, setAtEnd] = useState(!hasNext);
  const cursor = useRef(currentAt);
  const busy = useRef(false);
  const playingRef = useRef(false);
  const speedRef = useRef<AutoplaySpeed>(1);

  // The server's bar is the truth whenever the player is idle.
  useEffect(() => {
    if (!busy.current && !playingRef.current) {
      cursor.current = currentAt;
      setAtEnd(!hasNext);
    }
  }, [currentAt, hasNext]);

  const refresh = useCallback(() => {
    startTransition(() => router.refresh());
  }, [router]);

  /** One advance from the cursor. True when the session moved and can go on. */
  const stepOnce = useCallback(async (): Promise<"moved" | "retry" | "stop"> => {
    if (busy.current) return "stop";
    busy.current = true;
    try {
      const from = cursor.current;
      const result = await (step ?? autoplayStepAction)(sessionId, from);
      if (result.error) {
        setError(result.error);
        return "stop";
      }
      if (result.retryAfterMs) {
        await sleep(result.retryAfterMs);
        return "retry";
      }
      if (result.to && result.to !== from) {
        cursor.current = result.to;
        setAdvances((n) => n + 1);
        refresh();
      }
      if (result.status !== "active" || result.hasNext === false) {
        setAtEnd(true);
        return "stop";
      }
      return "moved";
    } finally {
      busy.current = false;
    }
  }, [refresh, sessionId, step]);

  const pause = useCallback(() => {
    playingRef.current = false;
    setPlaying(false);
  }, []);

  const play = useCallback(async () => {
    if (playingRef.current || busy.current) return;
    setError(null);
    playingRef.current = true;
    setPlaying(true);
    while (playingRef.current) {
      const started = now();
      const outcome = await stepOnce();
      if (outcome === "stop") break;
      const wait = autoplayDelayMs(speedRef.current) - (now() - started);
      if (wait > 0) await sleep(wait);
    }
    playingRef.current = false;
    setPlaying(false);
  }, [now, stepOnce]);

  const stepManually = useCallback(async () => {
    if (playingRef.current) pause();
    setError(null);
    await stepOnce();
  }, [pause, stepOnce]);

  const chooseSpeed = useCallback((next: AutoplaySpeed) => {
    speedRef.current = next;
    setSpeed(next);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey || isTyping(event.target)) return;
      if (event.key === " ") {
        // Space on a focused button or link is that control's own click.
        const el = event.target;
        if (el instanceof HTMLElement && (el.tagName === "BUTTON" || el.tagName === "A")) return;
        event.preventDefault();
        if (playingRef.current) pause();
        else if (!atEnd) void play();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        if (!atEnd) void stepManually();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        pause();
        return;
      }
      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        chooseSpeed(stepSpeed(speedRef.current, event.key === "ArrowUp" ? 1 : -1));
        return;
      }
      const picked = speedForKey(event.key);
      if (picked) chooseSpeed(picked);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [atEnd, chooseSpeed, pause, play, stepManually]);

  // Stop the loop when the player leaves the page.
  useEffect(
    () => () => {
      playingRef.current = false;
    },
    [],
  );

  return (
    <section
      aria-label="Autoplay"
      className="space-y-3"
      data-testid="replay-autoplay"
      data-advances={advances}
      data-playing={playing ? "true" : "false"}
      data-speed={speed}
    >
      <div className="flex flex-wrap items-center gap-2">
        {playing ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={pause}
            aria-keyshortcuts="Space"
          >
            <Pause className="size-4" aria-hidden /> Pause
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void play()}
            disabled={atEnd}
            aria-keyshortcuts="Space"
          >
            <Play className="size-4" aria-hidden /> Play
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void stepManually()}
          disabled={atEnd}
          aria-keyshortcuts="ArrowRight"
        >
          <StepForward className="size-4" aria-hidden /> Step
        </Button>
        <fieldset className="flex items-center gap-1" aria-label="Autoplay speed">
          <legend className="sr-only">Bars a second</legend>
          {AUTOPLAY_SPEEDS.map((value, index) => (
            <button
              key={value}
              type="button"
              aria-pressed={speed === value}
              aria-keyshortcuts={String(index + 1)}
              onClick={() => chooseSpeed(value)}
              className={cn(
                "h-8 min-w-10 rounded-md border px-2 text-xs tabular-nums",
                speed === value
                  ? "border-brand/50 bg-brand/10 font-semibold text-foreground"
                  : "border-border-muted text-text-secondary hover:text-foreground",
              )}
            >
              {value}×
            </button>
          ))}
        </fieldset>
      </div>
      <p className="text-xs leading-5 text-text-tertiary">
        {atEnd
          ? "Autoplay stops on the last bar; finishing the replay stays your click."
          : `Plays up to ${speed} bar${speed === 1 ? "" : "s"} a second, one step at a time. Keys: space plays or pauses, → steps, ← pauses, ↑ ↓ change speed, 1-4 pick it.`}
      </p>
      <p className="sr-only" aria-live="polite">
        {playing ? `Playing at ${speed} bars a second` : "Paused"}. {advances} steps so far.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      ) : null}
    </section>
  );
}
