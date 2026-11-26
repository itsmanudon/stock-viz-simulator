"use client";

/**
 * 3D tilt for the paper account card: it turns toward the pointer around
 * its centre, with a specular glare that follows. The card face itself is
 * untouched (its text is still text). Fine pointers with motion allowed
 * only; otherwise it is a plain wrapper.
 */

import { useEffect, useRef } from "react";

import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

export function TiltCard({
  children,
  className,
  max = 12,
}: {
  children: React.ReactNode;
  className?: string;
  max?: number;
}) {
  const outer = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const glare = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = outer.current;
    const card = inner.current;
    const light = glare.current;
    if (!host || !card || !light) return;
    if (!mediaMatches("(pointer: fine)") || mediaMatches("(prefers-reduced-motion: reduce)"))
      return;
    const onMove = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      card.style.transform = `rotateY(${(px - 0.5) * max * 2}deg) rotateX(${(0.5 - py) * max * 2}deg) translateZ(12px)`;
      light.style.opacity = "1";
      light.style.background = `radial-gradient(circle at ${px * 100}% ${py * 100}%, rgb(255 255 255 / 0.38), transparent 55%)`;
    };
    const onLeave = () => {
      card.style.transform = "";
      light.style.opacity = "0";
    };
    host.addEventListener("pointermove", onMove);
    host.addEventListener("pointerleave", onLeave);
    return () => {
      host.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerleave", onLeave);
    };
  }, [max]);

  return (
    <div ref={outer} className={cn("[perspective:900px]", className)}>
      <div
        ref={inner}
        className="relative transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] [transform-style:preserve-3d] will-change-transform"
      >
        {children}
        <div
          ref={glare}
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[1rem] opacity-0 mix-blend-overlay transition-opacity duration-300"
        />
      </div>
    </div>
  );
}
