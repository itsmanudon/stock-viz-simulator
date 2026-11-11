"use client";

/**
 * The landing hero's stage (design board option B).
 *
 * - The phone rotates through its screens every few seconds. Dots switch
 *   screens; hover pauses it; with reduced motion it never auto-advances.
 * - On wide screens with motion, the hero pins from the first scroll: the
 *   phone stops on Portfolio, the paper card lifts out of it, grows with a
 *   tilt, settles beside the "paper trading" copy, and flips to show its back.
 *   The hero is taller than the screen, so it rises into view as part of the
 *   same scrubbed timeline instead of scrolling up before the pin starts (the
 *   owner saw that as the phone "snapping" to the bottom of the screen).
 * - Everywhere else (phones, reduced motion, no JS) nothing pins, and the same
 *   copy is a plain section under the hero. Only one of the two copies is ever
 *   shown, so assistive technology reads it once.
 *
 * GSAP runs only here and in other marketing components; the product app does
 * not load it. `gsap.matchMedia` reverts every tween, split and pin when its
 * query stops matching or the component unmounts. The pinned section sits
 * inside a React-owned wrapper so GSAP's pin spacer never replaces a node
 * React removes.
 */

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { type ReactNode, useEffect, useRef, useState } from "react";

import type { PhoneScreen } from "@/components/marketing/hero-phone-screens";
import { PhoneFrame } from "@/components/marketing/phone-frame";
import { PaperCard } from "@/components/paper-card";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

const ROTATE_MS = 4500;
/** Scroll distance the pinned sequence takes, in viewport heights. */
const PIN_LENGTH = 1.5;

/** Layout offset of `el` inside `ancestor`, ignoring every CSS transform. */
function offsetWithin(el: HTMLElement, ancestor: HTMLElement): { x: number; y: number } {
  let x = 0;
  let y = 0;
  let node: HTMLElement | null = el;
  while (node && node !== ancestor) {
    x += node.offsetLeft;
    y += node.offsetTop;
    node = node.offsetParent as HTMLElement | null;
  }
  return { x, y };
}

export function HeroStage({
  lead,
  panel,
  pills,
  screens,
  intro,
}: {
  /** The centred copy above the stage: badge, h1, lede, buttons, chips. */
  lead: ReactNode;
  /** The real-data product panel behind the phone. */
  panel: ReactNode;
  /** Glass fact pills around the stage, from `lg` up. */
  pills: ReactNode;
  screens: PhoneScreen[];
  /** "What is paper trading?" copy, shown beside the card or as a section. */
  intro: ReactNode;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const deskRef = useRef<HTMLDivElement>(null);
  const phoneRef = useRef<HTMLDivElement>(null);
  const pillsRef = useRef<HTMLDivElement>(null);
  const dotsRef = useRef<HTMLDivElement>(null);
  const flyAnchorRef = useRef<HTMLDivElement>(null);
  const flyRef = useRef<HTMLDivElement>(null);
  const flyInnerRef = useRef<HTMLDivElement>(null);
  const copyRef = useRef<HTMLDivElement>(null);

  const [active, setActive] = useState(0);
  const [pinned, setPinned] = useState(false);
  // Refs, not state: the interval reads them without re-subscribing.
  const hold = useRef({ hover: false, scroll: false });

  useEffect(() => {
    if (screens.length < 2) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => {
      if (hold.current.hover || hold.current.scroll || document.hidden) return;
      setActive((index) => (index + 1) % screens.length);
    }, ROTATE_MS);
    return () => window.clearInterval(id);
  }, [screens.length]);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const heading = sectionRef.current?.querySelector("h1");
        if (heading) {
          // `aria: "auto"` labels the heading with its full text and hides the
          // word fragments, so it still reads as one sentence.
          const split = SplitText.create(heading, {
            type: "words",
            wordsClass: "split-word",
            aria: "auto",
          });
          gsap.from(split.words, {
            yPercent: 60,
            opacity: 0,
            duration: 0.8,
            stagger: 0.05,
            ease: "power3.out",
          });
        }
        // The entrance moves the inner elements, so the pinned timeline below
        // can own the outer ones from the start without the two fighting.
        gsap.from(deskRef.current?.firstElementChild ?? null, {
          y: 30,
          opacity: 0,
          duration: 1,
          ease: "power3.out",
          delay: 0.1,
        });
        gsap.from(phoneRef.current?.firstElementChild ?? null, {
          y: 60,
          opacity: 0,
          duration: 1,
          ease: "power3.out",
          delay: 0.25,
        });
      });

      mm.add("(prefers-reduced-motion: no-preference) and (min-width: 1024px)", () => {
        setPinned(true);
        const phone = phoneRef.current;
        const fly = flyRef.current;
        const flyInner = flyInnerRef.current;
        const anchor = flyAnchorRef.current;
        if (!phone || !fly || !flyInner || !anchor) return;

        const setOut = (out: boolean) => {
          hold.current.scroll = out;
          phone.toggleAttribute("data-card-out", out);
          gsap.set(fly, { autoAlpha: out ? 1 : 0 });
          if (out) setActive(0);
        };

        // Where the card sits inside the phone, relative to where it lands.
        // Measured from layout offsets, not bounding rects: ScrollTrigger
        // re-evaluates this on refresh, sometimes while the timeline has the
        // phone shrunk and sunk, and offsets ignore those GSAP transforms.
        const start = () => {
          const card = phone.querySelector<HTMLElement>("[data-phone-card]");
          if (!card || anchor.offsetWidth === 0) return { x: 0, y: 0, scale: 1 };
          const inPhone = offsetWithin(card, phone);
          // The anchor is centred with a CSS translate, which offsets also
          // ignore, so step back half its size to its visual top-left.
          const anchorX = anchor.offsetLeft - anchor.offsetWidth / 2;
          const anchorY = anchor.offsetTop - anchor.offsetHeight / 2;
          return {
            x: phone.offsetLeft + inPhone.x - anchorX,
            y: phone.offsetTop + inPhone.y - anchorY,
            scale: card.offsetWidth / anchor.offsetWidth,
          };
        };

        const section = sectionRef.current;
        const wrap = wrapRef.current;
        if (!section || !wrap) return;
        // How far the hero has to rise for its foot, where the card lands, to
        // reach the bottom of the screen. Offsets ignore the rise itself.
        const rise = () => Math.max(0, section.offsetHeight - window.innerHeight);
        // The rise leaves that much empty section at the bottom once the pin
        // releases; pulling the next section up by the same amount means it
        // arrives at the bottom of the screen exactly as the pin ends.
        const closeGap = () => {
          gsap.set(wrap, { marginBottom: -rise() });
        };

        const build = () => {
          closeGap();
          ScrollTrigger.addEventListener("refreshInit", closeGap);
          const tl = gsap.timeline({
            defaults: { ease: "none" },
            scrollTrigger: {
              trigger: section,
              start: "top top",
              end: () => `+=${Math.round(window.innerHeight * PIN_LENGTH)}`,
              pin: true,
              // Measured before every other trigger on the page: the space
              // this pin adds moves everything below it.
              refreshPriority: 1,
              scrub: 0.6,
              anticipatePin: 1,
              invalidateOnRefresh: true,
              onUpdate: (self) => setOut(self.progress > 0.004),
            },
          });
          tl.to(
            Array.from(section.children),
            { y: () => -rise(), duration: 0.42, ease: "power1.inOut" },
            0,
          )
            .to(pillsRef.current, { autoAlpha: 0, duration: 0.12 }, 0)
            .to(dotsRef.current, { autoAlpha: 0, duration: 0.12 }, 0)
            // The phone and panel sink out of view so nothing shows through
            // the copy that takes their place.
            .to(phone, { scale: 0.84, y: 220, autoAlpha: 0, duration: 0.38, ease: "power2.in" }, 0)
            .to(
              deskRef.current,
              { scale: 0.9, y: 160, autoAlpha: 0, duration: 0.38, ease: "power2.in" },
              0,
            )
            .fromTo(
              fly,
              { x: () => start().x, y: () => start().y, scale: () => start().scale },
              { x: 0, y: 0, scale: 1, duration: 0.42, ease: "power2.inOut" },
              0.02,
            )
            .to(
              flyInner,
              {
                keyframes: [
                  { rotateX: 24, rotateY: -26, rotateZ: -7, duration: 0.21, ease: "power1.out" },
                  { rotateX: 0, rotateY: 0, rotateZ: 0, duration: 0.21, ease: "power2.out" },
                ],
              },
              0.02,
            )
            .fromTo(
              copyRef.current,
              { autoAlpha: 0, x: 40 },
              { autoAlpha: 1, x: 0, duration: 0.16, ease: "power2.out" },
              0.42,
            )
            .to(flyInner, { rotateY: 180, duration: 0.22, ease: "power2.inOut" }, 0.66)
            .to({}, { duration: 0.12 });

          // The pin adds 1.5 viewport heights of scroll above every section
          // below the hero, but their triggers were measured at mount, before
          // this pin existed. Re-measure all of them, or scrubbed sections
          // further down (the "fill shows its work" step bar) run early and
          // look finished by the time they are on screen. Triggers refresh in
          // creation order, so the pin also gets refreshPriority and a sort.
          ScrollTrigger.sort();
          ScrollTrigger.refresh();
        };

        // Build almost at once: the pin starts on the first scroll, so a late
        // build would let the hero scroll freely and then jump into the pin.
        // The short wait lets React un-hide the card's landing spot first.
        const call = gsap.delayedCall(0.1, build);
        return () => {
          call.kill();
          ScrollTrigger.removeEventListener("refreshInit", closeGap);
          setOut(false);
          setPinned(false);
        };
      });
    },
    { scope: wrapRef },
  );

  const current = screens[active] ?? screens[0];

  return (
    <div ref={wrapRef}>
      <section ref={sectionRef} className="relative isolate overflow-hidden">
        {lead}

        <div className="relative mx-auto mt-12 w-full max-w-6xl px-4 sm:mt-16 sm:px-6">
          <div
            ref={stageRef}
            className="relative h-[33rem] overflow-hidden lg:h-[36rem]"
            onMouseEnter={() => {
              hold.current.hover = true;
            }}
            onMouseLeave={() => {
              hold.current.hover = false;
            }}
          >
            <div
              aria-hidden
              className="brand-glow top-6 left-1/2 -z-10 h-[34rem] w-[64rem] -translate-x-1/2"
            />

            <div ref={pillsRef} aria-hidden className="hidden lg:block">
              {pills}
            </div>

            <div ref={deskRef} className="absolute top-10 left-0 hidden w-[62%] lg:block">
              {panel}
            </div>

            {/* The phone always renders dark: it is a picture of the app's
                default theme, whichever theme the page is in. */}
            <div
              ref={phoneRef}
              aria-hidden
              className="dark absolute top-0 left-1/2 z-10 w-72 -translate-x-1/2 text-foreground lg:left-[61%] lg:translate-x-0 [&[data-card-out]_[data-phone-card]]:invisible"
            >
              <PhoneFrame screens={screens} active={active} />
            </div>

            {/* Landing spot for the card in the pinned sequence. */}
            <div
              ref={flyAnchorRef}
              aria-hidden
              hidden={!pinned}
              className="absolute top-1/2 left-[27%] z-20 w-[min(40%,27.5rem)] -translate-x-1/2 -translate-y-1/2"
            >
              <div ref={flyRef} className="invisible origin-top-left [perspective:1200px]">
                <div
                  ref={flyInnerRef}
                  className="relative aspect-[1.586] [transform-style:preserve-3d]"
                >
                  <PaperCard
                    currency="USD"
                    className="absolute inset-0 aspect-auto size-full shadow-[0_0_70px_color-mix(in_oklab,var(--brand-gradient-from)_55%,transparent)] [backface-visibility:hidden]"
                  />
                  <div className="absolute inset-0 flex flex-col justify-between rounded-2xl border border-brand-gradient-via/40 bg-linear-to-br from-[#141b2b] to-[#0a0f19] p-5 text-[#eef2f8] shadow-[0_0_60px_color-mix(in_oklab,var(--brand-gradient-from)_45%,transparent)] [backface-visibility:hidden] [transform:rotateY(180deg)]">
                    <span className="flex items-start justify-between">
                      <span className="text-lg font-semibold tracking-[-0.04em]">stockviz</span>
                      <span className="rounded-md border border-white/25 bg-black/25 px-1.5 py-0.5 font-mono text-3xs tracking-[0.08em]">
                        PAPER
                      </span>
                    </span>
                    <span className="grid gap-1.5 text-sm">
                      {["$100,000 paper balance", "No fees", "Fills at stored daily closes"].map(
                        (line) => (
                          <span key={line} className="flex items-center gap-2">
                            <span className="size-1.5 rounded-full bg-brand-gradient-via" />
                            {line}
                          </span>
                        ),
                      )}
                    </span>
                    <span className="font-mono text-3xs tracking-[0.06em] text-[#8892a4]">
                      NOT A REAL CARD · NOTHING REACHES AN EXCHANGE
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div
              ref={copyRef}
              hidden={!pinned}
              className="invisible absolute top-1/2 left-[53%] z-20 w-[40%] -translate-y-1/2 text-left"
            >
              {intro}
            </div>

            {screens.length > 1 ? (
              <div
                ref={dotsRef}
                className="glass absolute bottom-4 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2.5 rounded-full py-1.5 pr-2.5 pl-3.5 text-xs text-text-secondary"
              >
                <span aria-live="polite">{current?.label}</span>
                <span className="flex gap-1.5">
                  {screens.map((screen, index) => (
                    <button
                      key={screen.key}
                      type="button"
                      aria-label={`Show the ${screen.label.toLowerCase()} screen`}
                      aria-pressed={index === active}
                      onClick={() => setActive(index)}
                      className="h-2 w-2 rounded-full bg-surface-hover transition-[width,background-color] duration-300 aria-pressed:w-5 aria-pressed:bg-foreground"
                    />
                  ))}
                </span>
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {/* The same copy as a section of its own wherever the hero does not pin. */}
      <section
        hidden={pinned}
        aria-label="What is paper trading?"
        className="mx-auto grid w-full max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 md:grid-cols-2 md:py-24"
      >
        <div className="relative grid place-items-center">
          <div
            aria-hidden
            className="brand-glow top-1/2 left-1/2 -z-10 h-64 w-[min(24rem,100%)] -translate-1/2"
          />
          <PaperCard currency="USD" className="w-full max-w-sm" />
        </div>
        <div>{intro}</div>
      </section>
    </div>
  );
}
