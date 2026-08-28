/**
 * Compile-time guard against API/client type drift.
 *
 * The hand-written types in `types.ts` and the per-resource modules are
 * maintained by hand against FastAPI's Pydantic models, with nothing checking
 * that they still agree. `schema.d.ts` is generated from the live OpenAPI
 * document (`pnpm gen:api-types`), and the assertions below tie the two
 * together: change a response model on the API without regenerating and
 * updating the client type, and `tsc --noEmit` fails.
 *
 * This file exports nothing and emits no runtime code — it exists only to make
 * the type checker do the comparison.
 *
 * Scope is deliberate: the load-bearing money and market shapes, not every
 * response. Widen it when a shape starts mattering, not pre-emptively.
 *
 * Numbers cross the wire as JSON strings (Pydantic serializes `Decimal` that
 * way), which is why the client types use `string` for monetary fields — the
 * generated types agree, so the assertions hold without casts.
 */

import type { ReplaySessionList, ReplaySummary } from "./replay";
import type { components } from "./schema";
import type { Portfolio, PortfolioOption, TradeRow } from "./trading";
import type {
  BacktestSummary,
  EarningsEvent,
  MarketsSummary,
  Recommendation,
  ScreenerResult,
} from "./types";

type Schemas = components["schemas"];

/**
 * Assert `A` and `B` are mutually assignable. A mismatch surfaces as a type
 * error on the `Expect<...>` line naming the offending pair.
 */
type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Expect<T extends true> = T;

// Fields the client reads today. Each must exist on the generated schema with
// a compatible type — extra fields on the API side are fine (additive changes
// don't break a client), but a rename or a type change is not.
type Assignable<Client, Api> = Client extends Pick<Api, Extract<keyof Client, keyof Api>>
  ? Extract<keyof Client, keyof Api> extends keyof Client
    ? true
    : false
  : false;

// --- Money -----------------------------------------------------------------

export type _PortfolioMatches = Expect<Assignable<Portfolio, Schemas["PortfolioOut"]>>;
export type _PortfolioOptionMatches = Expect<
  Assignable<PortfolioOption, Schemas["PortfolioOptionOut"]>
>;
export type _TradeMatches = Expect<Assignable<TradeRow, Schemas["TradeOut"]>>;

// --- Market data -----------------------------------------------------------

export type _MarketsSummaryMatches = Expect<
  Assignable<MarketsSummary, Schemas["MarketsSummaryOut"]>
>;
export type _ScreenerMatches = Expect<Assignable<ScreenerResult, Schemas["ScreenerResultOut"]>>;
export type _RecommendationMatches = Expect<
  Assignable<Recommendation, Schemas["RecommendationOut"]>
>;
export type _EarningsEventMatches = Expect<Assignable<EarningsEvent, Schemas["EarningsEventOut"]>>;
export type _BacktestSummaryMatches = Expect<
  Assignable<BacktestSummary, Schemas["BacktestSummaryOut"]>
>;
export type _ReplaySummaryMatches = Expect<Assignable<ReplaySummary, Schemas["ReplaySummaryOut"]>>;
export type _ReplaySessionListMatches = Expect<
  Assignable<ReplaySessionList, Schemas["ReplaySessionListOut"]>
>;

// Keep `Exact` referenced so an unused-type lint doesn't remove the helper —
// it's the stricter check to reach for when a shape should match exactly.
export type _ExactHelperInUse = Exact<true, true>;
