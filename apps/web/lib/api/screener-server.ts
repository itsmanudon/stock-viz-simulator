import "server-only";

import type { ScreenerPage } from "./screener";
import { authedGet } from "./server";

/**
 * A3.3: the screener as the signed-in user. A rule that reads drawings
 * (`drawing()`, `avwap()`) runs only on its owner's drawings, so the page
 * sends the user's token when it runs a rule; the API refuses such a rule
 * signed out (401).
 */
export function getScreenerPageAsUser(query: URLSearchParams): Promise<ScreenerPage> {
  return authedGet<ScreenerPage>(`/v1/screener?${query.toString()}`);
}
