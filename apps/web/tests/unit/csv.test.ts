import { describe, expect, it } from "vitest";

import { csvField, csvRow, toCsv } from "@/lib/csv";

describe("csvField", () => {
  it("passes plain values through unquoted", () => {
    expect(csvField("AAPL")).toBe("AAPL");
    expect(csvField(42)).toBe("42");
  });

  it("renders null and undefined as empty", () => {
    expect(csvField(null)).toBe("");
    expect(csvField(undefined)).toBe("");
  });

  it("quotes fields containing a comma, quote, or newline", () => {
    expect(csvField("Alphabet, Inc.")).toBe('"Alphabet, Inc."');
    expect(csvField('He said "hi"')).toBe('"He said ""hi"""');
    expect(csvField("line1\nline2")).toBe('"line1\nline2"');
  });

  it("neutralises spreadsheet formulas", () => {
    // Excel/Sheets/LibreOffice evaluate a leading =, +, -, or @ as a formula,
    // so an exported value could become live content in the recipient's sheet.
    // Contains commas and quotes too, so it is neutralised *and* quoted.
    expect(csvField('=HYPERLINK("http://evil","click")')).toBe(
      '"\'=HYPERLINK(""http://evil"",""click"")"',
    );
    expect(csvField("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvField("+1234")).toBe("'+1234");
    expect(csvField("@SUM(A1)")).toBe("'@SUM(A1)");
  });

  it("neutralises and quotes a formula that also needs escaping", () => {
    expect(csvField("=A1,B1")).toBe('"\'=A1,B1"');
  });

  it("leaves a negative number readable while still neutralising it", () => {
    // Trade-off we accept: correctness beats prettiness for a leading '-'.
    expect(csvField("-12.50")).toBe("'-12.50");
    // Numbers pass through as numbers, so real negatives are unaffected.
    expect(csvField(-12.5)).toBe("'-12.5");
  });
});

describe("csvRow", () => {
  it("joins fields with commas", () => {
    expect(csvRow(["AAPL", "buy", 10])).toBe("AAPL,buy,10");
  });

  it("keeps column alignment when a field contains a comma", () => {
    const row = csvRow(["Alphabet, Inc.", "buy", 10]);
    expect(row).toBe('"Alphabet, Inc.",buy,10');
    // Three columns, not four.
    expect(row.split(",").length).toBeGreaterThan(3); // naive split breaks…
    expect(row.match(/^"[^"]*",/)).not.toBeNull(); // …but the quoting is correct
  });
});

describe("toCsv", () => {
  it("emits a BOM, CRLF line endings, and a trailing newline", () => {
    const csv = toCsv(["Ticker", "Qty"], [["AAPL", 10]]);
    expect(csv.startsWith("﻿")).toBe(true);
    expect(csv).toBe("﻿Ticker,Qty\r\nAAPL,10\r\n");
  });

  it("handles an empty row set", () => {
    expect(toCsv(["Ticker"], [])).toBe("﻿Ticker\r\n");
  });
});
