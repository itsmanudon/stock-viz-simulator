/**
 * Wire types mirroring the FastAPI Pydantic schemas in apps/api.
 *
 * Hand-typed for Phase 3. When the API surface stabilizes we'll swap to
 * openapi-typescript generation off /openapi.json — until then, keep this
 * file in sync with apps/api/src/stockviz/schemas.py.
 *
 * Numeric fields come over the wire as strings because the API uses
 * Decimal columns and pydantic serializes them as strings to preserve
 * precision. Parse to Number only at the render boundary.
 */

export type Health = {
  status: "ok" | "degraded";
  version: string;
  database: "up" | "down";
};

export type Symbol = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  // ISO-4217 currency the symbol trades in. Defaults to USD for the
  // historical universe; non-USD symbols (e.g. SAP.DE) declare it explicitly.
  currency: string;
  is_active: boolean;
};

export type Quote = {
  ticker: string;
  ts: string;
  close: string;
};

export type SymbolDetail = Symbol & {
  latest: Quote | null;
};

export type Bar = {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
};

export type Sentiment = "positive" | "neutral" | "negative";

export type NewsArticle = {
  id: number;
  ticker: string | null;
  title: string;
  url: string;
  source: string | null;
  published_at: string;
  summary: string | null;
  image_url: string | null;
  sentiment: Sentiment | null;
};

export type IndicatorPoint = {
  ts: string;
  value: number;
};

export type MACDPoint = {
  ts: string;
  macd: number;
  signal: number;
  histogram: number;
};

export type Indicators = {
  ticker: string;
  series: Record<string, IndicatorPoint[]>;
  macd: MACDPoint[] | null;
};

export type Recommendation = {
  ticker: string;
  name: string;
  sector: string | null;
  score: number;
  rationale: string[];
  computed_at: string;
};
