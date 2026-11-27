import "server-only";

/**
 * `/v1/broker/status` (A5.7, M1.7): what the app can do with each broker.
 * There is no live broker connection; the copy for each state is in
 * `lib/broker-status.ts`.
 */

import type { KiteHandoff } from "../basket";
import type { components } from "./schema";
import { authedGet } from "./server";

export type BrokerStatus = components["schemas"]["BrokerStatusOut"];
export type BrokerStatusItem = components["schemas"]["BrokerStatusItemOut"];

export function getBrokerStatus(): Promise<BrokerStatus> {
  return authedGet<BrokerStatus>("/v1/broker/status");
}

/** The status, or null when it could not be read: callers then say so, never an error page. */
export function getBrokerStatusOrNull(): Promise<BrokerStatus | null> {
  return getBrokerStatus().catch(() => null);
}

export type BasketHandoff = components["schemas"]["BasketHandoffOut"];

/**
 * A6.11: `/v1/broker/basket`. Kite's basket form is offered only when the
 * server has `KITE_API_KEY`; any failure means "off", never an error page.
 */
export async function getKiteHandoff(): Promise<KiteHandoff> {
  try {
    const out = await authedGet<BasketHandoff>("/v1/broker/basket");
    return out.kite_basket && out.kite_api_key && out.kite_basket_url
      ? { apiKey: out.kite_api_key, url: out.kite_basket_url }
      : null;
  } catch {
    return null;
  }
}
