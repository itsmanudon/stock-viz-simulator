"use client";

import { useRouter } from "next/navigation";
import { Tabs } from "radix-ui";
import type { ReactNode } from "react";

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
  optionCount,
  orderCount,
}: Props) {
  const router = useRouter();

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
      <div className="overflow-x-auto border-b border-border-muted">
        <Tabs.List aria-label="Portfolio sections" className="flex min-w-max gap-6 px-0.5 sm:gap-8">
          <Tab value="positions">Positions</Tab>
          <Tab value="options" count={optionCount}>
            Options
          </Tab>
          <Tab value="orders" count={orderCount}>
            Orders
          </Tab>
          <Tab value="income">Income</Tab>
        </Tabs.List>
      </div>

      <TabPanel value="positions">{positions}</TabPanel>
      <TabPanel value="options">{options}</TabPanel>
      <TabPanel value="orders">{orders}</TabPanel>
      <TabPanel value="income">{income}</TabPanel>
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
          <span className="ml-1.5 font-mono text-xs">{count}</span>
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
