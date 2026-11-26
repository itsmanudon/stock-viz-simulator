import { describe, expect, it } from "vitest";

import {
  MAX_TRADEBOOK_BYTES,
  checkTradebookFile,
  countItems,
  problemSkipsRow,
} from "./tradebook-import";

describe("checkTradebookFile", () => {
  it("accepts a CSV under the cap", () => {
    expect(checkTradebookFile({ name: "tradebook.csv", size: 1200, type: "text/csv" })).toBeNull();
    expect(
      checkTradebookFile({ name: "tradebook.CSV", size: 10, type: "application/vnd.ms-excel" }),
    ).toBeNull();
  });

  it("refuses empty, oversize, XLSX and non-CSV files", () => {
    expect(checkTradebookFile({ name: "a.csv", size: 0, type: "text/csv" })).toMatch(/empty/);
    expect(
      checkTradebookFile({ name: "a.csv", size: MAX_TRADEBOOK_BYTES + 1, type: "text/csv" }),
    ).toMatch(/2 MB/);
    expect(checkTradebookFile({ name: "a.xlsx", size: 10, type: "" })).toMatch(/XLSX/);
    expect(checkTradebookFile({ name: "a.pdf", size: 10, type: "application/pdf" })).toMatch(/CSV/);
  });
});

describe("countItems", () => {
  it("keeps rows and new, and only the other counts that are not zero", () => {
    const items = countItems({
      rows: 5,
      new: 2,
      posted: 2,
      needs_opening_lot: 0,
      duplicate: 1,
      unmatched: 0,
      skipped_segment: 1,
      rejected: 1,
      basis_uncertain: 0,
      intraday_inferred: 0,
    });
    expect(items.map((i) => i.label)).toEqual([
      "Rows",
      "New",
      "Already Imported or Repeated",
      "F&O Skipped",
      "Rejected",
    ]);
  });

  it("says which problems keep a row out", () => {
    expect(problemSkipsRow("rejected")).toBe(true);
    expect(problemSkipsRow("needs_opening_lot")).toBe(false);
    expect(problemSkipsRow("basis_uncertain")).toBe(false);
  });
});
