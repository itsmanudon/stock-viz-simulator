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
 */

const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"];

function neutralise(value: string): string {
  return FORMULA_PREFIXES.some((p) => value.startsWith(p)) ? `'${value}` : value;
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
