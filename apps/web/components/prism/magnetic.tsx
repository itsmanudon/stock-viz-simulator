"use client";

/**
 * Magnetic hover for a call to action: the child drifts a few pixels toward
 * the pointer while it is near, and springs back on leave. Fine pointers
 * with motion allowed only; otherwise it renders the child untouched.
 */

import { mediaMatches } from "@/lib/media";
import { useEffect, useRef } from "react";

export function Magnetic({
  children,
  strength = 0.3,
}: { children: React.ReactNode; strength?: number }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!mediaMatches("(pointer: fine)") || mediaMatches("(prefers-reduced-motion: reduce)"))
      return;
    const onMove = (event: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const dx = event.clientX - (rect.left + rect.width / 2);
      const dy = event.clientY - (rect.top + rect.height / 2);
      el.style.transform = `translate3d(${dx * strength}px, ${dy * strength}px, 0)`;
    };
    const onLeave = () => {
      el.style.transform = "";
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, [strength]);

  return (
    <span
      ref={ref}
      className="inline-flex transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] will-change-transform"
    >
      {children}
    </span>
  );
}
