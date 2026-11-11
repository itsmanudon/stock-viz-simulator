/**
 * The screens the hero phone rotates through, rendered on the server.
 *
 * Truth rules for a picture of the product:
 * - The portfolio screen has no real account behind it, so every figure on it
 *   is an example and the screen says "Example account".
 * - The stock and order-review screens use the same stored bars as the hero
 *   panel: the real latest close, its date and the real one-day change. The
 *   review's quantity of 1 is the only example value, and it is stated.
 * - The news screen shows real stored headlines with only what StockViz knows
 *   about them (source and publish date). It claims no verification, which
 *   arrives with the Aegis feed. With no stored headlines it is left out.
 *
 * The phone is decorative (`aria-hidden` in HeroStage); every fact it shows is
 * also on the page as text or in the real product.
 */

import {
  ArrowLeft,
  ArrowLeftRight,
  Bell,
  FlaskConical,
  ListOrdered,
  Lock,
  Search,
  Star,
} from "lucide-react";
import type { ReactNode } from "react";

import { type PanelData, loadPanel } from "@/components/marketing/hero-panel";
import { PaperCard } from "@/components/paper-card";
import { Sparkline } from "@/components/sparkline";
import { ApiError, getNewsForTicker } from "@/lib/api";
import type { NewsArticle } from "@/lib/api/types";
import { formatCurrency, splitMinorUnits } from "@/lib/portfolio-view-model";
import { describeFillRule, formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export type PhoneScreenKey = "portfolio" | "stock" | "review" | "news";

export type PhoneScreen = {
  key: PhoneScreenKey;
  /** Shown beside the dots under the phone. */
  label: string;
  /** Which tab the phone's tab bar highlights for this screen. */
  tab: "Home" | "Markets" | "News";
  node: ReactNode;
};

/** A headline figure with the cents dimmed, the Revolut balance treatment. */
function Figure({ value, className }: { value: string; className?: string }) {
  const [major, minor] = splitMinorUnits(value);
  return (
    <span className={cn("font-mono tracking-tight", className)} data-financial>
      {major}
      {minor ? <span className="figure-minor">{minor}</span> : null}
    </span>
  );
}

function RoundIcon({ children }: { children: ReactNode }) {
  return (
    <span className="grid size-8 place-items-center rounded-full border border-border-muted bg-surface-secondary">
      {children}
    </span>
  );
}

/* Example holdings. Not real positions: the screen is labelled as an example. */
const EXAMPLE_HOLDINGS = [
  { ticker: "AAPL", detail: "10 shares", value: "$2,684.70", change: "+1.18%", up: true },
  { ticker: "NVDA", detail: "25 shares", value: "$4,812.50", change: "-0.64%", up: false },
  { ticker: "MSFT", detail: "6 shares", value: "$3,052.86", change: "+0.27%", up: true },
];

function PortfolioScreen() {
  return (
    <>
      <div className="flex items-center justify-between">
        <RoundIcon>
          <span className="text-xs">A</span>
        </RoundIcon>
        <div className="flex gap-2">
          <RoundIcon>
            <Search className="size-3.5" />
          </RoundIcon>
          <RoundIcon>
            <Bell className="size-3.5" />
          </RoundIcon>
        </div>
      </div>
      {/* `data-phone-card` is what the pinned hero measures and lifts out. */}
      <div data-phone-card>
        <PaperCard currency="USD" className="w-full" />
      </div>
      <div className="grid justify-items-center gap-0.5 text-center">
        <span className="flex items-center gap-1.5 text-2xs text-text-tertiary">
          Portfolio value
          <span className="rounded border border-warning/40 px-1 font-mono text-3xs tracking-wider text-warning">
            EXAMPLE ACCOUNT
          </span>
        </span>
        <Figure value="$106,482.17" className="text-3xl font-medium" />
        <span className="font-mono text-2xs text-positive">▲ +$1,204.55 (+1.14%) today</span>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {[
          { icon: ArrowLeftRight, label: "Trade" },
          { icon: ListOrdered, label: "Orders" },
          { icon: FlaskConical, label: "Backtest" },
          { icon: Bell, label: "Alerts" },
        ].map(({ icon: Icon, label }) => (
          <span
            key={label}
            className="grid justify-items-center gap-1 text-3xs text-text-secondary"
          >
            <span className="grid size-10 place-items-center rounded-full border border-border-muted bg-surface-secondary">
              <Icon className="size-4" />
            </span>
            {label}
          </span>
        ))}
      </div>
      <div className="glass rounded-2xl px-3 py-2">
        <p className="mb-1 text-2xs text-text-secondary">Holdings</p>
        {EXAMPLE_HOLDINGS.map((row) => (
          <div
            key={row.ticker}
            className="flex items-center justify-between border-t border-border-muted py-1.5 first:border-t-0"
          >
            <span>
              <span className="block text-xs font-medium">{row.ticker}</span>
              <span className="block text-3xs text-text-tertiary">{row.detail}</span>
            </span>
            <span className="text-right font-mono text-2xs">
              <span className="block">{row.value}</span>
              <span className={row.up ? "text-positive" : "text-negative"}>
                {row.up ? "▲ " : "▼ "}
                {row.change}
              </span>
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

function stockFacts(data: PanelData) {
  const closes = data.bars.map((bar) => Number(bar.close));
  const close = closes[closes.length - 1];
  const previous = closes[closes.length - 2];
  const change = close - previous;
  const changePct = previous ? (change / previous) * 100 : 0;
  return {
    closes,
    close,
    change,
    changePct,
    up: change >= 0,
    closeDate: formatCloseDate(data.bars[data.bars.length - 1]?.ts),
    price: formatCurrency(close, data.currency),
  };
}

function StockScreen({ data }: { data: PanelData }) {
  const facts = stockFacts(data);
  return (
    <>
      <div className="flex items-center justify-between">
        <RoundIcon>
          <ArrowLeft className="size-3.5" />
        </RoundIcon>
        <span className="text-sm font-medium">{data.ticker}</span>
        <RoundIcon>
          <Star className="size-3.5" />
        </RoundIcon>
      </div>
      <div className="grid gap-0.5">
        <span className="truncate text-2xs text-text-tertiary">
          {data.name} · {data.currency}
        </span>
        <Figure value={facts.price} className="text-3xl font-medium" />
        <span className={cn("font-mono text-2xs", facts.up ? "text-positive" : "text-negative")}>
          {facts.up ? "▲ " : "▼ "}
          {formatCurrency(Math.abs(facts.change), data.currency)} (
          {Math.abs(facts.changePct).toFixed(2)}%) · 1 day
        </span>
      </div>
      {facts.closeDate ? (
        <span className="w-max rounded-full border border-border-muted bg-card px-2.5 py-1 text-3xs text-text-secondary">
          Close of record · {facts.closeDate}
        </span>
      ) : null}
      <Sparkline closes={facts.closes} showBaseline className="h-32 w-full" />
      <div className="flex justify-between rounded-full border border-border-muted bg-card p-0.5 font-mono text-3xs">
        {["1W", "1M", "3M", "1Y", "5Y"].map((range) => (
          <span
            key={range}
            className={cn(
              "flex-1 rounded-full py-1 text-center",
              range === "3M" ? "bg-surface-hover text-foreground" : "text-text-tertiary",
            )}
          >
            {range}
          </span>
        ))}
      </div>
      <div className="mt-auto grid grid-cols-2 gap-2 pb-2">
        <span className="rounded-full border border-border-muted bg-surface-secondary py-2.5 text-center text-xs font-semibold">
          Sell
        </span>
        <span className="rounded-full bg-primary py-2.5 text-center text-xs font-semibold text-primary-foreground">
          Buy
        </span>
      </div>
    </>
  );
}

function ReviewScreen({ data }: { data: PanelData }) {
  const facts = stockFacts(data);
  const rows: [string, string][] = [
    ["Quantity", `1 ${data.ticker}`],
    ["Reference price", `${facts.price}${facts.closeDate ? ` · ${facts.closeDate}` : ""}`],
    ["Fees", "None in the simulator"],
  ];
  return (
    <>
      <div className="flex items-center justify-between">
        <RoundIcon>
          <ArrowLeft className="size-3.5" />
        </RoundIcon>
        <span className="text-sm font-medium">Review order</span>
        <span className="size-8" />
      </div>
      <div className="grid gap-1 pt-2">
        <Figure value={`−${facts.price}`} className="text-3xl font-medium" />
        <span className="text-xs text-text-secondary">Market buy 1 {data.ticker} · example</span>
      </div>
      <dl className="divide-y divide-border-muted rounded-xl border border-border-muted bg-card text-2xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 px-3 py-2">
            <dt className="text-text-tertiary">{label}</dt>
            <dd className="text-right font-mono">{value}</dd>
          </div>
        ))}
        <div className="px-3 py-2">
          <dt className="text-text-tertiary">How it fills</dt>
          <dd className="mt-0.5 leading-4">{describeFillRule("market")}</dd>
        </div>
      </dl>
      <p className="flex items-center gap-1.5 text-3xs text-text-tertiary">
        <Lock className="size-3" />
        Paper trade. No real money moves.
      </p>
      <div className="mt-auto grid grid-cols-[auto_1fr] gap-2 pb-2">
        <span className="rounded-full border border-border-muted px-4 py-2.5 text-xs font-semibold">
          Edit
        </span>
        <span className="rounded-full bg-primary py-2.5 text-center text-xs font-semibold text-primary-foreground">
          Place buy order
        </span>
      </div>
    </>
  );
}

function NewsScreen({ ticker, articles }: { ticker: string; articles: NewsArticle[] }) {
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="text-lg font-medium tracking-tight">News</span>
        <span className="rounded-full border border-border-muted px-2 py-0.5 font-mono text-3xs">
          {ticker}
        </span>
      </div>
      {articles.map((article) => (
        <div key={article.id} className="glass grid gap-1.5 rounded-2xl p-3">
          <span className="flex flex-wrap gap-1.5 text-3xs text-text-tertiary">
            {article.source ? <span>{article.source}</span> : null}
            {article.source ? <span aria-hidden>·</span> : null}
            <span className="font-mono">{formatCloseDate(article.published_at)}</span>
          </span>
          <span className="line-clamp-3 text-xs leading-4">{article.title}</span>
        </div>
      ))}
    </>
  );
}

async function loadArticles(ticker: string): Promise<NewsArticle[]> {
  try {
    return (await getNewsForTicker(ticker, 2)).slice(0, 2);
  } catch (err) {
    if (err instanceof ApiError) return [];
    throw err;
  }
}

/** Portfolio always comes first: the pinned hero lifts the card out of it. */
export async function loadPhoneScreens(): Promise<PhoneScreen[]> {
  const screens: PhoneScreen[] = [
    { key: "portfolio", label: "Portfolio", tab: "Home", node: <PortfolioScreen /> },
  ];

  const data = await loadPanel();
  if (!data || data.bars.length < 2) return screens;

  screens.push(
    { key: "stock", label: "Stock page", tab: "Markets", node: <StockScreen data={data} /> },
    { key: "review", label: "Order review", tab: "Markets", node: <ReviewScreen data={data} /> },
  );

  const articles = await loadArticles(data.ticker);
  if (articles.length > 0) {
    screens.push({
      key: "news",
      label: "News",
      tab: "News",
      node: <NewsScreen ticker={data.ticker} articles={articles} />,
    });
  }
  return screens;
}
