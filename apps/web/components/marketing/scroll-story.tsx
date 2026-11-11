"use client";

/**
 * Scroll story: four short steps on the left, a phone on the right that stays
 * on screen (CSS sticky) and shows the screen for the step being read.
 *
 * Switching the screen is state, not motion, so it happens with or without
 * reduced motion; only the cross-fade between screens is animated (CSS, and
 * stopped by the global reduced-motion rule). Below `lg` the phone is hidden
 * and the steps read as a plain list, all at full strength. Steps are drawn
 * only for screens the hero could build, so a step never describes a screen
 * that is missing (news, when nothing is stored). `overflow-x-clip`, not
 * `hidden`, keeps the glow inside the page without breaking the sticky phone.
 */

import { useEffect, useRef, useState } from "react";

import type { PhoneScreen, PhoneScreenKey } from "@/components/marketing/hero-phone-screens";
import { PhoneFrame } from "@/components/marketing/phone-frame";
import { cn } from "@/lib/utils";

const STEPS: Record<PhoneScreenKey, { chip: string; title: string; soft: string; body: string }> = {
  portfolio: {
    chip: "Your account",
    title: "Start with $100,000.",
    soft: "Watch what it becomes.",
    body: "Your paper balance, what you hold and how it moved, valued at the latest stored closes.",
  },
  stock: {
    chip: "Research",
    title: "Every price says",
    soft: "which close it is.",
    body: "Charts, indicators and headlines on one page, with the close of record dated down to the year.",
  },
  review: {
    chip: "Review",
    title: "See the whole order",
    soft: "before you place it.",
    body: "Amount, reference close, fees and the fill rule on one screen. Edit it or place it; nothing goes through without the review.",
  },
  news: {
    chip: "News",
    title: "Headlines for",
    soft: "what you hold.",
    body: "Stored news for each symbol, with its source and publish date.",
  },
};

export function ScrollStory({ screens }: { screens: PhoneScreen[] }) {
  const [active, setActive] = useState(0);
  const [enhanced, setEnhanced] = useState(false);
  const stepRefs = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    setEnhanced(true);
    // A step becomes active as it crosses the middle of the viewport.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = stepRefs.current.indexOf(entry.target as HTMLLIElement);
          if (index >= 0) setActive(index);
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    for (const step of stepRefs.current) if (step) observer.observe(step);
    return () => observer.disconnect();
  }, []);

  if (screens.length < 2) return null;

  return (
    <section
      aria-labelledby="story-heading"
      className="mx-auto grid w-full max-w-6xl gap-14 overflow-x-clip px-4 py-16 sm:px-6 lg:grid-cols-[minmax(0,1fr)_18rem]"
    >
      <h2 id="story-heading" className="sr-only">
        What a session looks like in the app
      </h2>
      <ol className="grid gap-12 lg:gap-0">
        {screens.map((screen, index) => {
          const step = STEPS[screen.key];
          return (
            <li
              key={screen.key}
              ref={(node) => {
                stepRefs.current[index] = node;
              }}
              className={cn(
                "grid content-center gap-3.5 transition-opacity duration-300 lg:min-h-[62vh]",
                enhanced && index !== active && "lg:opacity-35",
              )}
            >
              <span className="w-max rounded-full border border-border-muted bg-surface-secondary px-3 py-1 text-xs text-text-secondary">
                {String(index + 1).padStart(2, "0")} · {step.chip}
              </span>
              <h3 className="text-3xl font-medium tracking-[-0.03em] text-balance sm:text-4xl">
                {step.title} <span className="text-text-tertiary">{step.soft}</span>
              </h3>
              <p className="max-w-lg text-base leading-7 text-text-secondary">{step.body}</p>
            </li>
          );
        })}
      </ol>
      <div
        aria-hidden
        className="sticky top-[9vh] hidden h-[40rem] self-start lg:grid lg:place-items-center"
      >
        <div className="brand-glow top-1/2 left-1/2 -z-10 h-96 w-96 -translate-1/2 opacity-60" />
        <div className="grid justify-items-center gap-3.5">
          <PhoneFrame screens={screens} active={active} className="dark w-72 text-foreground" />
          <div className="flex gap-1.5">
            {screens.map((screen, index) => (
              <span
                key={screen.key}
                className={cn(
                  "h-0.5 w-6 rounded-full",
                  index <= active ? "bg-foreground" : "bg-border",
                )}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
