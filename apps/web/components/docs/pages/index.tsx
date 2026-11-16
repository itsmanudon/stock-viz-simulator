import type { ComponentType } from "react";

import { Alerts } from "@/components/docs/pages/alerts";
import { Backtests } from "@/components/docs/pages/backtests";
import { GettingStarted } from "@/components/docs/pages/getting-started";
import { GlossaryFaq } from "@/components/docs/pages/glossary-faq";
import { HowFiguresAreMeasured } from "@/components/docs/pages/how-figures-are-measured";
import { MarketsAndStocks } from "@/components/docs/pages/markets-and-stocks";
import { NewsReactions } from "@/components/docs/pages/news-reactions";
import { OptionStrategies } from "@/components/docs/pages/option-strategies";
import { Options } from "@/components/docs/pages/options";
import { Orders } from "@/components/docs/pages/orders";
import { Portfolio } from "@/components/docs/pages/portfolio";
import { Replay } from "@/components/docs/pages/replay";
import { ReturnsAndRisk } from "@/components/docs/pages/returns-and-risk";
import { ScreenerCompare } from "@/components/docs/pages/screener-compare";
import { Signals } from "@/components/docs/pages/signals";

/** Content for each /docs page, by slug (lib/docs/nav.ts lists them). */
export const DOC_CONTENT: Record<string, ComponentType> = {
  "getting-started": GettingStarted,
  orders: Orders,
  options: Options,
  "option-strategies": OptionStrategies,
  "markets-and-stocks": MarketsAndStocks,
  "screener-and-compare": ScreenerCompare,
  signals: Signals,
  backtests: Backtests,
  "news-reactions": NewsReactions,
  replay: Replay,
  portfolio: Portfolio,
  "returns-and-risk": ReturnsAndRisk,
  alerts: Alerts,
  "how-figures-are-measured": HowFiguresAreMeasured,
  "glossary-and-faq": GlossaryFaq,
};
