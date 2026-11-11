"use client";

/**
 * Scroll motion for the landing sections below the hero.
 *
 * The sections stay server components and mark what should move with
 * `data-motion` attributes; this wrapper finds them and animates them with
 * GSAP. With reduced motion (or before this runs, or without JS) every
 * section is already complete: nothing here is needed to read the page.
 *
 * - `data-motion="words"`: a heading rises word by word (SplitText, with
 *   `aria: "auto"` so it still reads as one sentence).
 * - `data-motion="rise"`: its `[data-motion-item]` children slide up in turn.
 * - `data-motion="draw"`: its SVG paths draw themselves.
 * - `data-motion="count"`: counts up to `data-value` (`data-decimals`,
 *   `data-prefix`, `data-suffix` shape the text; the server text is final).
 * - `data-motion="steps"`: `[data-step-line]` fill and `[data-step]` light up
 *   in turn as the section scrolls past (all lit without motion).
 * - `data-motion="glow"`: a glow rises and brightens with scroll.
 */

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { type ReactNode, useRef } from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

const ONCE = { start: "top 88%", once: true } as const;

export function LandingMotion({ children }: { children: ReactNode }) {
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const root = scope.current;
      if (!root) return;
      const all = <T extends Element = HTMLElement>(selector: string) =>
        Array.from(root.querySelectorAll<T & Element>(selector));

      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const cleanups: (() => void)[] = [];
        for (const heading of all('[data-motion="words"]')) {
          const split = SplitText.create(heading, {
            type: "words",
            wordsClass: "split-word",
            aria: "auto",
          });
          gsap.from(split.words, {
            yPercent: 60,
            opacity: 0,
            duration: 0.7,
            stagger: 0.035,
            ease: "power3.out",
            scrollTrigger: { trigger: heading, ...ONCE },
          });
        }

        for (const group of all('[data-motion="rise"]')) {
          gsap.from(group.querySelectorAll("[data-motion-item]"), {
            y: 44,
            opacity: 0,
            duration: 0.7,
            stagger: 0.08,
            ease: "power3.out",
            scrollTrigger: { trigger: group, ...ONCE },
          });
        }

        for (const group of all('[data-motion="draw"]')) {
          for (const path of Array.from(group.querySelectorAll<SVGPathElement>("path"))) {
            const length = path.getTotalLength();
            gsap.fromTo(
              path,
              { strokeDasharray: length, strokeDashoffset: length },
              {
                strokeDashoffset: 0,
                duration: 1.4,
                ease: "power2.out",
                scrollTrigger: { trigger: group, ...ONCE },
              },
            );
          }
        }

        for (const el of all('[data-motion="count"]')) {
          const target = Number(el.dataset.value);
          if (!Number.isFinite(target)) continue;
          const decimals = Number(el.dataset.decimals ?? 0);
          const prefix = el.dataset.prefix ?? "";
          const suffix = el.dataset.suffix ?? "";
          const final = el.textContent;
          const counter = { value: 0 };
          gsap.to(counter, {
            value: target,
            duration: 1.4,
            ease: "power2.out",
            scrollTrigger: { trigger: el, ...ONCE },
            onUpdate: () => {
              el.textContent = `${prefix}${counter.value.toFixed(decimals)}${suffix}`;
            },
            onComplete: () => {
              el.textContent = final;
            },
          });
        }

        for (const section of all('[data-motion="steps"]')) {
          const lines = Array.from(section.querySelectorAll<HTMLElement>("[data-step-line]"));
          const steps = Array.from(section.querySelectorAll<HTMLElement>("[data-step]"));
          const count = Math.max(1, lines.length);
          const update = (progress: number) => {
            const p = progress * count;
            lines.forEach((line, i) => {
              line.style.setProperty("--p", String(Math.max(0, Math.min(1, p - i))));
            });
            const activeIndex = Math.min(count, Math.floor(p + 0.5));
            for (const step of steps) {
              const i = Number(step.dataset.step);
              step.dataset.on = String(
                step.hasAttribute("data-step-pill") ? i <= activeIndex : i === activeIndex,
              );
            }
          };
          update(0);
          ScrollTrigger.create({
            trigger: section,
            start: "top 80%",
            end: "bottom 45%",
            scrub: true,
            onUpdate: (self) => update(self.progress),
          });
          cleanups.push(() => {
            // Leave every step lit when motion stops, the static state.
            for (const line of lines) line.style.removeProperty("--p");
            for (const step of steps) step.dataset.on = "true";
          });
        }

        for (const glow of all('[data-motion="glow"]')) {
          gsap.fromTo(
            glow,
            { yPercent: 45, scale: 0.7, opacity: 0.2 },
            {
              yPercent: 0,
              scale: 1,
              opacity: 1,
              ease: "none",
              scrollTrigger: {
                trigger: glow.parentElement,
                start: "top 90%",
                end: "center 50%",
                scrub: 0.5,
              },
            },
          );
        }

        return () => {
          for (const cleanup of cleanups) cleanup();
        };
      });
    },
    { scope },
  );

  return <div ref={scope}>{children}</div>;
}
