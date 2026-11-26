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
  | "basis_uncertain";

export const PROBLEM_LABELS: Record<ProblemKind, string> = {
  rejected: "Rejected",
  segment: "F&O or Other Segment",
  unmatched: "Unknown Symbol",
  duplicate_in_file: "Repeated in File",
  already_imported: "Already Imported",
  needs_opening_lot: "Needs Opening Lot",
  basis_uncertain: "Basis Uncertain",
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
  basis_uncertain: number;
  intraday_inferred: number;
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
    { label: "Basis Uncertain", value: c.basis_uncertain },
    { label: "Intraday (Inferred)", value: c.intraday_inferred },
  ];
  return items.filter((i) => i.keep || i.value > 0).map(({ label, value }) => ({ label, value }));
}

export const PRODUCT_LABELS: Record<string, string> = {
  delivery: "Delivery",
  intraday: "Intraday",
  mixed: "Part Intraday",
};
