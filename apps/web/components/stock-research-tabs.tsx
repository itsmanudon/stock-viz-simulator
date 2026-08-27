"use client";

import { Tabs } from "radix-ui";
import type { ReactNode } from "react";

export function StockResearchTabs({
  overview,
  news,
  positionOrders,
  discussion,
  newsCount = 0,
  orderCount = 0,
}: {
  overview: ReactNode;
  news: ReactNode;
  positionOrders: ReactNode;
  discussion: ReactNode;
  newsCount?: number;
  orderCount?: number;
}) {
  return (
    <Tabs.Root defaultValue="overview" className="min-w-0">
      <Tabs.List
        aria-label="Stock research sections"
        className="flex gap-6 overflow-x-auto border-b border-border-muted"
      >
        <Tab value="overview">Overview</Tab>
        <Tab value="news">News{newsCount ? ` ${newsCount}` : ""}</Tab>
        <Tab value="position-orders">Position &amp; orders{orderCount ? ` ${orderCount}` : ""}</Tab>
        <Tab value="discussion">Discussion</Tab>
      </Tabs.List>
      <TabPanel value="overview">{overview}</TabPanel>
      <TabPanel value="news">{news}</TabPanel>
      <TabPanel value="position-orders">{positionOrders}</TabPanel>
      <TabPanel value="discussion">{discussion}</TabPanel>
    </Tabs.Root>
  );
}

function Tab({ value, children }: { value: string; children: ReactNode }) {
  return (
    <Tabs.Trigger
      value={value}
      className="relative shrink-0 py-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:text-foreground data-[state=active]:after:absolute data-[state=active]:after:inset-x-0 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:bg-brand"
    >
      {children}
    </Tabs.Trigger>
  );
}

function TabPanel({ value, children }: { value: string; children: ReactNode }) {
  return (
    <Tabs.Content
      value={value}
      className="py-6 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </Tabs.Content>
  );
}
