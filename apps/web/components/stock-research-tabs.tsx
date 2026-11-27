"use client";

import { Tabs } from "radix-ui";
import type { ReactNode } from "react";

export function StockResearchTabs({
  overview,
  financials,
  options,
  research,
  news,
  positionOrders,
  newsCount = 0,
  orderCount = 0,
  initialTab,
}: {
  overview: ReactNode;
  /** Phase 6.4: statements and key metrics. */
  financials?: ReactNode;
  /** A7.9: gamma and delta exposure, when a US chain snapshot exists. */
  options?: ReactNode;
  /** A9: seasonality, earnings drift and the other research views. */
  research?: ReactNode;
  news: ReactNode;
  positionOrders: ReactNode;
  newsCount?: number;
  orderCount?: number;
  /** A7.13: `?tab=` from a desk link; ignored when that tab is not shown. */
  initialTab?: string;
}) {
  const shown: Record<string, boolean> = {
    overview: true,
    financials: Boolean(financials),
    options: Boolean(options),
    research: Boolean(research),
    news: true,
    "position-orders": true,
  };
  const start = initialTab && shown[initialTab] ? initialTab : "overview";
  return (
    <Tabs.Root defaultValue={start} className="min-w-0">
      <Tabs.List
        aria-label="Stock research sections"
        className="flex gap-5 overflow-x-auto border-b border-border-muted sm:gap-7"
      >
        <Tab value="overview">Overview</Tab>
        {financials ? <Tab value="financials">Financials</Tab> : null}
        {options ? <Tab value="options">Options</Tab> : null}
        {research ? <Tab value="research">Research</Tab> : null}
        <Tab value="news">News{newsCount ? ` ${newsCount}` : ""}</Tab>
        <Tab value="position-orders">Position &amp; orders{orderCount ? ` ${orderCount}` : ""}</Tab>
      </Tabs.List>
      <TabPanel value="overview">{overview}</TabPanel>
      {financials ? <TabPanel value="financials">{financials}</TabPanel> : null}
      {options ? <TabPanel value="options">{options}</TabPanel> : null}
      {research ? <TabPanel value="research">{research}</TabPanel> : null}
      <TabPanel value="news">{news}</TabPanel>
      <TabPanel value="position-orders">{positionOrders}</TabPanel>
    </Tabs.Root>
  );
}

function Tab({ value, children }: { value: string; children: ReactNode }) {
  return (
    <Tabs.Trigger
      value={value}
      className="relative shrink-0 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:text-foreground data-[state=active]:after:absolute data-[state=active]:after:inset-x-0 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:bg-brand"
    >
      {children}
    </Tabs.Trigger>
  );
}

function TabPanel({ value, children }: { value: string; children: ReactNode }) {
  return (
    <Tabs.Content
      value={value}
      className="py-5 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:py-6"
    >
      {children}
    </Tabs.Content>
  );
}
