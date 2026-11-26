/**
 * Title Case for interface labels (owner, 26 Nov 2026): the site uses Title
 * Case wherever it used to set text in capitals: eyebrows, table and field
 * labels, badges, chips. Text is never transformed with CSS `uppercase` any
 * more; labels are written in Title Case, and dynamic ones go through
 * `titleCase()`.
 *
 * Rules (Chicago-style, kept simple):
 * - Capitalise the first letter of every word.
 * - Short articles, conjunctions and prepositions stay lower case unless they
 *   start or end the label ("Return vs Hold", "Sign In to Save").
 * - A word that already has a capital after its first letter, or is all
 *   capitals, is left exactly as written. That keeps the conventions that
 *   stay in capitals: ticker symbols (AAPL, RELIANCE), exchange codes (NSE,
 *   NASDAQ), currency codes (USD, INR), time zones (UTC) and financial
 *   abbreviations (P&L, P/E, RSI, MACD, SMA, ROE, XIRR, VaR, MAE, EOD).
 * - Each part of a hyphenated word is capitalised ("52-Week", "Buy-and-Hold").
 * - Units written in lower case on purpose stay that way: "bn", "x", "bps".
 */

const MINOR = new Set([
  "a",
  "an",
  "and",
  "as",
  "at",
  "but",
  "by",
  "for",
  "from",
  "in",
  "into",
  "nor",
  "of",
  "on",
  "or",
  "per",
  "the",
  "to",
  "via",
  "vs",
  "with",
]);

/** Lower-case units and symbols that must never be capitalised. */
const KEEP_LOWER = new Set(["bn", "x", "bps", "pp", "mo", "wk", "t"]);

function capitalise(part: string): string {
  // Leave acronyms, tickers and mixed-case words (iPhone, P&L, VaR) alone.
  const letters = part.replace(/[^A-Za-z]/g, "");
  if (letters.length >= 2 && letters === letters.toUpperCase()) return part;
  if (/[a-z].*[A-Z]/.test(part) || /^[A-Z][a-z]*[A-Z]/.test(part)) return part;
  const index = part.search(/[A-Za-z]/);
  if (index < 0) return part;
  return part.slice(0, index) + part.charAt(index).toUpperCase() + part.slice(index + 1);
}

/** Verbs whose particle is part of the verb ("Sign In", "Log Out"), not a preposition. */
const PHRASAL = new Set(["sign", "log", "check", "set", "opt", "roll", "buy", "sell", "cash"]);

function convertWord(word: string, first: boolean, last: boolean, previous: string): string {
  const bare = word.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, "");
  const lowerBare = bare.toLowerCase();
  if (KEEP_LOWER.has(bare) || lowerBare === "vs") return word;
  if (/^\d/.test(bare) && !bare.includes("-")) return word;
  const particle = ["in", "out", "up", "off", "on", "back"].includes(lowerBare);
  const afterVerb = PHRASAL.has(previous.replace(/[^A-Za-z]/g, "").toLowerCase());
  if (particle && afterVerb) return capitalise(word);
  if (!first && !last && MINOR.has(lowerBare) && bare === lowerBare) return word;
  // Hyphenated words: title-case every part except minor words inside.
  if (bare.includes("-")) {
    return word
      .split("-")
      .map((part, i, all) => {
        const p = part.toLowerCase();
        if (i > 0 && i < all.length - 1 && MINOR.has(p)) return part;
        return capitalise(part);
      })
      .join("-");
  }
  return capitalise(word);
}

/**
 * Convert an interface label to Title Case, keeping acronyms and tickers.
 * Anything that is not a non-empty string (a number, a React element, null)
 * is returned unchanged, so it can wrap any rendered label safely.
 */
export function titleCase<T>(value: T): T {
  if (typeof value !== "string" || !value) return value;
  const text: string = value;
  // Split on spaces only, so separators like "·" and "/" stay where they are.
  const words = text.split(/(\s+)/);
  const indexes = words.map((w, i) => (/\S/.test(w) ? i : -1)).filter((i) => i >= 0);
  // A separator (·, /, —) between words starts a new phrase.
  let phraseStart = true;
  let previous = "";
  return words
    .map((word, i) => {
      if (!/\S/.test(word)) return word;
      if (!/[A-Za-z0-9]/.test(word)) {
        phraseStart = true;
        previous = "";
        return word;
      }
      const position = indexes.indexOf(i);
      const nextWord = words[indexes[position + 1]] ?? "";
      const last = position === indexes.length - 1 || !/[A-Za-z0-9]/.test(nextWord);
      const out = convertWord(word, phraseStart, last, previous);
      phraseStart = false;
      previous = word;
      return out;
    })
    .join("") as T;
}
