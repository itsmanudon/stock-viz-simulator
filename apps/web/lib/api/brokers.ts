import "server-only";

/**
 * `/v1/broker/status` (A5.7, M1.7): what the app can do with each broker.
 * There is no live broker connection; the copy for each state is in
 * `lib/broker-status.ts`.
 */

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
