/**
 * CSV serialisation.
 *
 * Two things a naive `values.join(",")` gets wrong:
 *
 * 1. **Quoting.** A field containing a comma, quote, or newline corrupts every
 *    column after it. RFC 4180 says wrap in double quotes and double any
 *    embedded quote.
 * 2. **Formula injection.** Excel, Sheets, and LibreOffice evaluate a cell
 *    beginning with `=`, `+`, `-`, `@`, or a tab/CR as a formula, so a value
 *    like `=HYPERLINK(...)` becomes live content in the recipient's
 *    spreadsheet. Prefixing with a single quote neutralises it.
 *
 * Today every field comes from our own database, so this is defence in depth
 * rather than a live hole — but a user-supplied portfolio name or ticker note
 * would make it one.
 *
 * The one exception is a leading `-` on a value that is entirely a number.
 * Negative amounts are ordinary data here (realized P&L, cash movements), and
 * prefixing them turns every one into a text cell that Excel will not sum —
 * which defeats the point of exporting to a spreadsheet. A bare negative
 * number cannot carry a payload, so exempting it costs nothing; anything a
 * spreadsheet would evaluate as an expression is not a number and is still
 * neutralised.
 */

const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"];

/**
 * A field that is entirely a finite number, e.g. `-12.50` or `-1e3`.
 *
 * Only a leading `-` is exempted below, and only for these: a bare negative
 * number cannot carry a payload, because anything a spreadsheet would treat
 * as an expression (`-1+1`, `-HYPERLINK(...)`) fails this test and is still
 * neutralised. `=`, `+`, `@`, tab and CR are never exempt.
 */
function isPlainNumber(value: string): boolean {
  return value.trim() !== "" && Number.isFinite(Number(value));
}

function neutralise(value: string): string {
  if (!FORMULA_PREFIXES.some((p) => value.startsWith(p))) return value;
  // Negative amounts are ordinary data in a financial export. Prefixing them
  // makes every negative P&L a text cell, so the column cannot be summed or
  // charted — the export's whole purpose. Exempt them, but only when the
  // field parses as a number and therefore cannot be an expression.
  if (value.startsWith("-") && isPlainNumber(value)) return value;
  return `'${value}`;
}

/** Quote and escape one CSV field. */
export function csvField(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const raw = neutralise(String(value));
  if (/[",\n\r]/.test(raw)) {
    return `"${raw.replace(/"/g, '""')}"`;
  }
  return raw;
}

/** Join one row's fields. */
export function csvRow(fields: Array<string | number | null | undefined>): string {
  return fields.map(csvField).join(",");
}

/**
 * Build a full CSV document.
 *
 * Uses CRLF line endings (RFC 4180) and prepends a UTF-8 BOM so Excel opens
 * non-ASCII company names correctly instead of mojibake.
 */
export function toCsv(
  header: string[],
  rows: Array<Array<string | number | null | undefined>>,
): string {
  return `﻿${[csvRow(header), ...rows.map(csvRow)].join("\r\n")}\r\n`;
}
