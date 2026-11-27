"use client";

/**
 * Plays the background music (`lib/sound/ambient.ts`) on the public pages
 * while interface sound is on. Mounted once in the public layout, so it
 * never plays inside the workspace and stops when someone signs in.
 *
 * - Waits for a first press or key in the page: browsers will not start
 *   audio before one, and someone who turned sound on last visit should not
 *   be met by music they did not start this time.
 * - Not on the log-in and sign-up forms.
 * - Fades out while the tab is hidden and back in when it returns.
 */

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { setAmbientMood, startAmbient, stopAmbient } from "@/lib/sound/ambient";

import { useSound } from "./sound-provider";

const QUIET_PATHS = ["/login", "/signup"];

export function AmbientMusic() {
  const { enabled } = useSound();
  const pathname = usePathname();
  const quiet = QUIET_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  useEffect(() => {
    if (!enabled || quiet) return;
    let disposed = false;
    const play = () => {
      if (!disposed && document.visibilityState === "visible") startAmbient();
    };
    const onVisibility = () => (document.visibilityState === "visible" ? play() : stopAmbient());
    const onFirstGesture = () => play();

    const activation = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } })
      .userActivation;
    if (activation?.hasBeenActive) play();
    else {
      window.addEventListener("pointerdown", onFirstGesture, { once: true });
      window.addEventListener("keydown", onFirstGesture, { once: true });
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      window.removeEventListener("pointerdown", onFirstGesture);
      window.removeEventListener("keydown", onFirstGesture);
      document.removeEventListener("visibilitychange", onVisibility);
      stopAmbient();
    };
  }, [enabled, quiet]);

  return null;
}

/** Sets the music's mood from a breadth share while mounted (the hero). */
export function AmbientMood({ share }: { share: number | null }) {
  useEffect(() => {
    setAmbientMood(share);
    return () => setAmbientMood(null);
  }, [share]);
  return null;
}
