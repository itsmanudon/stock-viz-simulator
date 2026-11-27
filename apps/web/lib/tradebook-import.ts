/**
 * A5.3: client-safe helpers for the tradebook import page: the file check the
 * browser and the server action share, and the labels for the preview's
 * problems and counts. No value from the file is ever shown beyond the
 * parsed fields the API returns.
 */

export const MAX_TRADEBOOK_BYTES = 2 * 1024 * 1024;

const CSV_TYPES = new Set([
  "",
  "text/csv",
  "text/plain",
  "application/csv",
  "application/vnd.ms-excel",
  "application/octet-stream",
]);

/** Why the chosen file can't be sent, or null when it can. */
export function checkTradebookFile(file: { name: string; size: number; type: string }):
  | string
  | null {
  if (file.size === 0) return "The file is empty";
  if (file.size > MAX_TRADEBOOK_BYTES) return "The file is larger than 2 MB";
  const name = file.name.toLowerCase();
  if (name.endsWith(".xlsx") || name.endsWith(".xls")) {
    return "Download the tradebook as CSV, not XLSX, and choose that file";
  }
  if (!name.endsWith(".csv") && !CSV_TYPES.has(file.type)) {
    return "Choose a CSV file (the tradebook downloaded as CSV)";
  }
  return null;
}

export type ProblemKind =
  | "rejected"
  | "segment"
  | "unmatched"
  | "duplicate_in_file"
  | "already_imported"
  | "needs_opening_lot"
  | "basis_uncertain"
  | "not_executed";

export const PROBLEM_LABELS: Record<ProblemKind, string> = {
  rejected: "Rejected",
  segment: "F&O or Other Segment",
  unmatched: "Unknown Symbol",
  duplicate_in_file: "Repeated in File",
  already_imported: "Already Imported",
  needs_opening_lot: "Needs Opening Lot",
  basis_uncertain: "Basis Uncertain",
  not_executed: "Not Executed",
};

/** Problems that keep a row out of the book (the others still import, flagged). */
export function problemSkipsRow(kind: ProblemKind): boolean {
  return kind !== "needs_opening_lot" && kind !== "basis_uncertain";
}

export type ImportCounts = {
  rows: number;
  new: number;
  posted: number;
  needs_opening_lot: number;
  duplicate: number;
  unmatched: number;
  skipped_segment: number;
  rejected: number;
  /** A6.11: orders in the file that did not execute (an order-status column). */
  not_executed?: number;
  basis_uncertain: number;
  intraday_inferred: number;
  /** Sells posted as intraday shorts: covered by buys of the scrip the same day. */
  intraday_short?: number;
};

/** The preview's summary line, in reading order; zero counts after `new` are left out. */
export function countItems(c: ImportCounts): { label: string; value: number }[] {
  const items: { label: string; value: number; keep?: boolean }[] = [
    { label: "Rows", value: c.rows, keep: true },
    { label: "New", value: c.new, keep: true },
    { label: "Need Opening Lot", value: c.needs_opening_lot },
    { label: "Already Imported or Repeated", value: c.duplicate },
    { label: "Unknown Symbol", value: c.unmatched },
    { label: "F&O Skipped", value: c.skipped_segment },
    { label: "Rejected", value: c.rejected },
    { label: "Not Executed", value: c.not_executed ?? 0 },
    { label: "Basis Uncertain", value: c.basis_uncertain },
    { label: "Intraday (Inferred)", value: c.intraday_inferred },
    { label: "Intraday Short", value: c.intraday_short ?? 0 },
  ];
  return items.filter((i) => i.keep || i.value > 0).map(({ label, value }) => ({ label, value }));
}

export const PRODUCT_LABELS: Record<string, string> = {
  delivery: "Delivery",
  intraday: "Intraday",
  mixed: "Part Intraday",
};

// --- A6.11: broker maps and "Map columns yourself" ---------------------------------

/** The brokers an imported book can name, in the order Settings lists them. */
export const IMPORT_BROKERS = [
  { value: "zerodha", label: "Zerodha" },
  { value: "dhan", label: "Dhan" },
  { value: "fyers", label: "Fyers" },
  { value: "upstox", label: "Upstox" },
  { value: "angelone", label: "Angel One" },
  { value: "groww", label: "Groww" },
  { value: "other", label: "Other Broker (Map Columns Yourself)" },
] as const;

export type ImportBroker = (typeof IMPORT_BROKERS)[number]["value"];

export function brokerLabel(broker: string | null | undefined): string {
  const found = IMPORT_BROKERS.find((b) => b.value === broker);
  if (!found) return "Broker";
  return found.value === "other" ? "Other Broker" : found.label;
}

/**
 * The currency an imported book is created in: an Indian broker's tradebook
 * is in rupees; an "other" book (the user's own map) takes the chosen
 * currency, so a US broker's file goes into a USD book.
 */
export function importedBookCurrency(broker: string, chosen: "USD" | "INR"): "USD" | "INR" {
  return broker === "other" ? chosen : "INR";
}

/** `?map=` and `?custom_map=` for preview and commit; "auto" detects from the header row. */
export function importQuery(choice: string): { map?: string; custom_map?: number } {
  if (choice.startsWith("saved:")) {
    const id = Number(choice.slice(6));
    return Number.isSafeInteger(id) && id > 0 ? { custom_map: id } : {};
  }
  if (choice && choice !== "auto" && /^[a-z0-9_]+$/.test(choice)) return { map: choice };
  return {};
}

export function importQueryString(choice: string): string {
  const q = importQuery(choice);
  const params = new URLSearchParams();
  if (q.map) params.set("map", q.map);
  if (q.custom_map) params.set("custom_map", String(q.custom_map));
  const text = params.toString();
  return text ? `&${text}` : "";
}

export function normaliseHeader(header: string): string {
  return header
    .replace(/\uFEFF/g, "")
    .trim()
    .replace(/^"|"$/g, "")
    .toLowerCase()
    .replace(/[\s_\-./]+/g, "");
}

const GUESSES: Record<string, string[]> = {
  trade_date: ["tradedate", "date", "tradeday", "settlementdate", "rundate"],
  executed_at: ["datetime", "dateandtime", "executiontime", "tradetime", "time", "filledtime"],
  symbol: ["symbol", "ticker", "tradingsymbol", "scrip", "scripname", "stock", "stockname", "name"],
  exchange: ["exchange", "exch", "exchangesegment", "market", "venue"],
  side: ["side", "action", "buysell", "transactiontype", "type", "tradetype", "bs"],
  quantity: ["quantity", "qty", "shares", "units", "tradedquantity", "filledquantity"],
  price: ["price", "tradeprice", "tradedprice", "fillprice", "rate", "averageprice"],
  trade_id: ["tradeid", "tradeno", "tradenumber", "executionid", "fillid", "exchangetradeid"],
  order_id: ["orderid", "orderno", "ordernumber", "exchangeorderid"],
  isin: ["isin", "isincode"],
};

/**
 * A first guess at the user's own map from the file's header row: each field
 * takes the first header whose name it recognises, and no header twice. The
 * user corrects it before saving.
 */
export function guessMapping(headers: string[]): Record<string, string> {
  const used = new Set<string>();
  const out: Record<string, string> = {};
  for (const [field, names] of Object.entries(GUESSES)) {
    for (const name of names) {
      const hit = headers.find((h) => normaliseHeader(h) === name && !used.has(h));
      if (hit) {
        out[field] = hit;
        used.add(hit);
        break;
      }
    }
  }
  return out;
}

/** The fields of "Map columns yourself", in form order. */
export const MAP_FIELDS: { field: string; label: string; required: boolean }[] = [
  { field: "trade_date", label: "Trade Date", required: false },
  { field: "executed_at", label: "Execution Time", required: false },
  { field: "symbol", label: "Symbol", required: true },
  { field: "exchange", label: "Exchange", required: false },
  { field: "side", label: "Side (Buy or Sell)", required: true },
  { field: "quantity", label: "Quantity", required: true },
  { field: "price", label: "Price", required: true },
  { field: "trade_id", label: "Trade ID", required: false },
  { field: "order_id", label: "Order ID", required: false },
  { field: "isin", label: "ISIN", required: false },
];

const FIELD_LABEL = Object.fromEntries(MAP_FIELDS.map((f) => [f.field, f.label]));

/** Why a mapping can't be saved yet (the API checks it again), or null. */
export function mappingProblem(mapping: Record<string, string>): string | null {
  const missing: string[] = [];
  for (const f of MAP_FIELDS) {
    if (f.required && !mapping[f.field]) missing.push(f.label);
  }
  if (!mapping.trade_date && !mapping.executed_at) missing.push("Trade Date or Execution Time");
  if (missing.length) return `Map these fields: ${missing.join(", ")}`;
  const seen = new Map<string, string>();
  for (const [field, header] of Object.entries(mapping)) {
    if (!header) continue;
    const key = normaliseHeader(header);
    const other = seen.get(key);
    if (other) {
      return `${FIELD_LABEL[other] ?? other} and ${FIELD_LABEL[field] ?? field} read the same header: pick one each`;
    }
    seen.set(key, field);
  }
  return null;
}

/** The market's time zone for showing an imported trade's time. */
export function marketZone(market: string): { timeZone: string; label: string } {
  return market === "us"
    ? { timeZone: "America/New_York", label: "ET" }
    : { timeZone: "Asia/Kolkata", label: "IST" };
}

/**
 * The header row of a CSV's text (its first non-empty line), split on commas
 * (or semicolons or tabs when the line has no comma), quotes honoured. Read
 * in the browser, so "Map columns yourself" can start before any upload.
 */
export function headerRowFromText(text: string): string[] {
  const line = text
    .replace(/^﻿/, "")
    .split(/\r?\n/)
    .find((l) => l.trim() !== "");
  if (!line) return [];
  const delimiter = line.includes(",")
    ? ","
    : line.includes(";")
      ? ";"
      : line.includes("\t")
        ? "\t"
        : ",";
  const out: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delimiter) {
      out.push(cell.trim());
      cell = "";
    } else cell += ch;
  }
  out.push(cell.trim());
  return out
    .filter((h) => h !== "")
    .map((h) => h.slice(0, 60))
    .slice(0, 60);
}
