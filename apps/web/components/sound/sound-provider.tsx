"use client";

/**
 * Opt-in interface sound (PRISM redesign).
 *
 * Off by default, and off until the person presses the sound switch: the
 * choice is remembered in this browser only. While on, one delegated listener
 * gives buttons, tabs and links a soft tap, pointer hover over navigation a
 * faint tick, and a route change a short "air" sweep. Components that finish
 * something meaningful (an order filled, an alert saved, a failed submit) call
 * `emitSound("fill")` etc., which is a no-op while sound is off.
 *
 * Sound never carries information on its own: every sound accompanies a
 * visible change that already says the same thing.
 */

import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { type SoundName, playSound, primeSound } from "@/lib/sound/engine";

const STORAGE_KEY = "stockviz:sound";
const EVENT = "stockviz:sound";

type SoundContextValue = {
  enabled: boolean;
  setEnabled: (on: boolean) => void;
  play: (name: SoundName) => void;
};

const SoundContext = createContext<SoundContextValue>({
  enabled: false,
  setEnabled: () => {},
  play: () => {},
});

export function useSound() {
  return useContext(SoundContext);
}

/** Fire-and-forget from anywhere in the client (no hook needed). */
export function emitSound(name: SoundName) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SoundName>(EVENT, { detail: name }));
}

const TAP_TARGETS =
  'button, a[href], [role="tab"], [role="menuitem"], [role="switch"], [role="option"], summary, input[type="checkbox"], input[type="radio"]';
const HOVER_TARGETS = 'nav a[href], [data-sound-hover], [role="tab"]';

function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

export function SoundProvider({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabledState] = useState(false);
  const enabledRef = useRef(false);
  const pathname = usePathname();
  const firstPath = useRef(true);

  useEffect(() => {
    const stored = readStored();
    enabledRef.current = stored;
    setEnabledState(stored);
  }, []);

  const setEnabled = useCallback((on: boolean) => {
    enabledRef.current = on;
    setEnabledState(on);
    try {
      window.localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
    } catch {
      // Private mode: the choice lasts for this page only.
    }
    if (on) {
      primeSound();
      playSound("toggleOn");
    }
  }, []);

  const play = useCallback((name: SoundName) => {
    if (enabledRef.current) playSound(name);
  }, []);

  // Delegated taps and hovers.
  useEffect(() => {
    let lastHover: Element | null = null;

    function onClick(event: MouseEvent) {
      if (!enabledRef.current) return;
      const target = (event.target as Element | null)?.closest?.(TAP_TARGETS);
      if (!target) return;
      const custom = target.getAttribute("data-sound");
      if (custom === "none") return;
      playSound((custom as SoundName) || "tap");
    }

    function onOver(event: PointerEvent) {
      if (!enabledRef.current || event.pointerType !== "mouse") return;
      const target = (event.target as Element | null)?.closest?.(HOVER_TARGETS) ?? null;
      if (target === lastHover) return;
      lastHover = target;
      if (target && target.getAttribute("data-sound") !== "none") playSound("hover");
    }

    function onEmit(event: Event) {
      const name = (event as CustomEvent<SoundName>).detail;
      if (enabledRef.current && name) playSound(name);
    }

    document.addEventListener("click", onClick, { capture: true });
    document.addEventListener("pointerover", onOver, { passive: true });
    window.addEventListener(EVENT, onEmit);
    return () => {
      document.removeEventListener("click", onClick, { capture: true });
      document.removeEventListener("pointerover", onOver);
      window.removeEventListener(EVENT, onEmit);
    };
  }, []);

  // A soft sweep on each client-side page change.
  // biome-ignore lint/correctness/useExhaustiveDependencies: the path changing is the event; its value is not read.
  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false;
      return;
    }
    if (enabledRef.current) playSound("navigate");
  }, [pathname]);

  const value = useMemo(() => ({ enabled, setEnabled, play }), [enabled, setEnabled, play]);
  return <SoundContext.Provider value={value}>{children}</SoundContext.Provider>;
}

/**
 * Plays `success` when `ok` turns into a new truthy value and `error` when
 * `failed` does. For form outcomes from `useActionState`: pass the success
 * payload (or message) and the error string. Silent while sound is off.
 */
export function useOutcomeSound(ok: unknown, failed: unknown, success: SoundName = "success") {
  const lastOk = useRef(ok);
  const lastFailed = useRef(failed);
  useEffect(() => {
    if (ok && ok !== lastOk.current) emitSound(success);
    lastOk.current = ok;
  }, [ok, success]);
  useEffect(() => {
    if (failed && failed !== lastFailed.current) emitSound("error");
    lastFailed.current = failed;
  }, [failed]);
}
