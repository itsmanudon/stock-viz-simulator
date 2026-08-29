"use client";

/**
 * Scroll-reveal wrapper for the marketing pages.
 *
 * Deliberately not a motion library: the whole effect is one opacity/translate
 * transition declared in `globals.css`, and this component only flips the
 * `data-reveal` attribute the first time the element enters the viewport. The
 * repo has no animation dependency and this doesn't justify adding one.
 *
 * Content is never *gated* behind the observer — reduced motion, a missing
 * IntersectionObserver, and no-JS (handled by a `scripting: none` rule in the
 * stylesheet) all resolve to the visible state.
 */

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

type Props = {
  children: React.ReactNode;
  className?: string;
  /**
   * Stagger in milliseconds. Multiply by the item index at the call site —
   * keeping the arithmetic there means a list can pick its own step without
   * this component knowing anything about the collection.
   */
  delay?: number;
  /** Element to render. Lists need `li` to keep the `ul` markup valid. */
  as?: "div" | "li" | "section";
};

export function Reveal({ children, className, delay = 0, as: Tag = "div" }: Props) {
  const ref = useRef<HTMLElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    // Skip straight to the final state when motion is unwelcome or the API
    // isn't there, rather than leaving the subtree at opacity 0 forever.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          // One-shot: nothing re-hides on scroll back up.
          observer.disconnect();
        }
      },
      // Fire slightly before the element is fully in view so the transition
      // finishes around the time the reader reaches it.
      { rootMargin: "0px 0px -10% 0px", threshold: 0.05 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as React.Ref<never>}
      data-reveal={shown ? "shown" : "pending"}
      style={delay > 0 ? { transitionDelay: `${delay}ms` } : undefined}
      className={cn(className)}
    >
      {children}
    </Tag>
  );
}
