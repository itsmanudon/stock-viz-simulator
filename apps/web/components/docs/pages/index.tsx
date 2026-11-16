import type { ComponentType } from "react";

import { GettingStarted } from "@/components/docs/pages/getting-started";
import { OptionStrategies } from "@/components/docs/pages/option-strategies";
import { Options } from "@/components/docs/pages/options";
import { Orders } from "@/components/docs/pages/orders";

/** Content for each /docs page, by slug (lib/docs/nav.ts lists them). */
export const DOC_CONTENT: Record<string, ComponentType> = {
  "getting-started": GettingStarted,
  orders: Orders,
  options: Options,
  "option-strategies": OptionStrategies,
};
