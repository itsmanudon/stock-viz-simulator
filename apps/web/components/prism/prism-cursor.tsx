"use client";

/**
 * Public-site cursor: a hollow ring that trails the pointer and a dot that
 * sits exactly on it. Over a link or button the ring swells into a solid
 * disc (difference-blended, so the label under it inverts and stays
 * readable); over text fields it becomes a caret.
 *
 * Only for fine pointers and only with motion allowed. The system cursor is
 * never hidden, so precision and accessibility tools keep working; this is
 * an accent around it, not a replacement.
 */

import { mediaMatches } from "@/lib/media";
import { useEffect, useRef, useState } from "react";

export function PrismCursor() {
  const ringRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (
      !mediaMatches("(pointer: fine)") ||
      !mediaMatches("(prefers-reduced-motion: no-preference)")
    )
      return;
    setActive(true);
  }, []);

  useEffect(() => {
    if (!active) return;
    const ring = ringRef.current;
    const dot = dotRef.current;
    if (!ring || !dot) return;
    let x = -100;
    let y = -100;
    let rx = -100;
    let ry = -100;
    let frame = 0;
    let shown = false;

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      x = event.clientX;
      y = event.clientY;
      dot.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      if (!shown) {
        shown = true;
        rx = x;
        ry = y;
        ring.style.opacity = "1";
        dot.style.opacity = "1";
      }
      const target = event.target as Element | null;
      const state = target?.closest?.(
        'input:not([type="range"]):not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]',
      )
        ? "text"
        : target?.closest?.(
              'a[href], button, [role="button"], [role="tab"], summary, label, select',
            )
          ? "link"
          : "idle";
      if (ring.dataset.state !== state) ring.dataset.state = state;
    };
    const onLeave = () => {
      shown = false;
      ring.style.opacity = "0";
      dot.style.opacity = "0";
    };
    const tick = () => {
      rx += (x - rx) * 0.18;
      ry += (y - ry) * 0.18;
      ring.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, [active]);

  if (!active) return null;
  return (
    <>
      <div
        ref={ringRef}
        aria-hidden
        className="prism-cursor"
        data-state="idle"
        style={{ opacity: 0 }}
      />
      <div ref={dotRef} aria-hidden className="prism-cursor-dot" style={{ opacity: 0 }} />
    </>
  );
}
