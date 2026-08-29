"use client";

/**
 * Sticky shell for the public header.
 *
 * The bar floats as a rounded pill and only grows its border, blur, and shadow
 * once the page has scrolled — at rest it sits transparent on the hero so the
 * page opens without a hard rule across the top.
 *
 * This is the only client piece of the header: everything inside it (the nav,
 * the session-aware CTA, the market-status chip) stays server-rendered and is
 * passed through as `children`.
 */

import { useEffect, useState } from "react";

/** Matches the pill's vertical offset, so the state flips as it leaves the top. */
const SCROLL_THRESHOLD = 24;

export function FloatingHeader({ children }: { children: React.ReactNode }) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > SCROLL_THRESHOLD);
    // Run once: a reload partway down the page must not start at rest.
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className="sticky top-0 z-40 px-3 pt-3 sm:px-4">
      <div
        data-scrolled={scrolled}
        className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 rounded-full border border-transparent px-3 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-300 sm:px-4 data-[scrolled=true]:border-border-muted data-[scrolled=true]:bg-background/70 data-[scrolled=true]:shadow-lg data-[scrolled=true]:shadow-black/5 data-[scrolled=true]:backdrop-blur-xl"
      >
        {children}
      </div>
    </header>
  );
}
