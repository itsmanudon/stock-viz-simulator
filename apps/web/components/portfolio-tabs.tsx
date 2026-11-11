"use client";

import { useRouter } from "next/navigation";
import { Tabs } from "radix-ui";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { CountBadge } from "@/components/count-badge";
import {
  type PortfolioRange,
  type PortfolioTab,
  buildPortfolioHref,
} from "@/lib/portfolio-view-model";

type Props = {
  activeTab: PortfolioTab;
  range: PortfolioRange;
  positions: ReactNode;
  options: ReactNode;
  orders: ReactNode;
  income: ReactNode;
  news: ReactNode;
  journal: ReactNode;
  positionCount: number;
  optionCount: number;
  orderCount: number;
};

export function PortfolioTabs({
  activeTab,
  range,
  positions,
  options,
  orders,
  income,
  news,
  journal,
  positionCount,
  optionCount,
  orderCount,
}: Props) {
  const router = useRouter();
  const scroller = useRef<HTMLDivElement>(null);
  // Which edges have more tabs past them (UI audit P3). On the narrowest
  // phones the row still scrolls; a fade on that edge says so.
  const [more, setMore] = useState({ start: false, end: false });

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const update = () =>
      setMore({
        start: el.scrollLeft > 4,
        end: el.scrollLeft + el.clientWidth < el.scrollWidth - 4,
      });
    // Bring an active tab that starts off-screen into view. scrollLeft, not
    // scrollIntoView, so the page itself never scrolls.
    const active = el.querySelector<HTMLElement>('[data-state="active"]');
    if (active && active.offsetLeft + active.offsetWidth > el.clientWidth) {
      el.scrollLeft = active.offsetLeft + active.offsetWidth - el.clientWidth;
    }
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, []);

  function selectTab(value: string) {
    router.push(
      buildPortfolioHref({
        range,
        tab: value as PortfolioTab,
      }),
      { scroll: false },
    );
  }

  return (
    <Tabs.Root value={activeTab} onValueChange={selectTab} className="min-w-0">
      <div
        ref={scroller}
        data-more-start={more.start || undefined}
        data-more-end={more.end || undefined}
        className="overflow-x-auto border-b border-border-muted [scrollbar-width:none] data-[more-end]:[mask-image:linear-gradient(to_right,black_calc(100%-2.5rem),transparent)] data-[more-start]:[mask-image:linear-gradient(to_left,black_calc(100%-2.5rem),transparent)] data-[more-start]:data-[more-end]:[mask-image:linear-gradient(to_right,transparent,black_2.5rem,black_calc(100%-2.5rem),transparent)] [&::-webkit-scrollbar]:hidden"
      >
        <Tabs.List aria-label="Portfolio sections" className="flex min-w-max gap-3 px-0.5 sm:gap-8">
          <Tab value="positions" count={positionCount}>
            Positions
          </Tab>
          <Tab value="options" count={optionCount}>
            Options
          </Tab>
          <Tab value="orders" count={orderCount}>
            Orders
          </Tab>
          <Tab value="income">Income</Tab>
          <Tab value="news">News</Tab>
          <Tab value="journal">Journal</Tab>
        </Tabs.List>
      </div>

      <TabPanel value="positions">{positions}</TabPanel>
      <TabPanel value="options">{options}</TabPanel>
      <TabPanel value="orders">{orders}</TabPanel>
      <TabPanel value="income">{income}</TabPanel>
      <TabPanel value="news">{news}</TabPanel>
      <TabPanel value="journal">{journal}</TabPanel>
    </Tabs.Root>
  );
}

function Tab({
  value,
  count,
  children,
}: {
  value: PortfolioTab;
  count?: number;
  children: ReactNode;
}) {
  return (
    <Tabs.Trigger
      value={value}
      className="relative shrink-0 py-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[state=active]:text-foreground data-[state=active]:after:absolute data-[state=active]:after:inset-x-0 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:bg-brand"
    >
      {children}
      {count ? (
        <>
          {" "}
          <CountBadge count={count} />
        </>
      ) : null}
    </Tabs.Trigger>
  );
}

function TabPanel({ value, children }: { value: PortfolioTab; children: ReactNode }) {
  return (
    <Tabs.Content
      value={value}
      className="py-5 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:py-6"
    >
      {children}
    </Tabs.Content>
  );
}
