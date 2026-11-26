import { describe, expect, it } from "vitest";

import { csvCell } from "../../../frontend/src/lib/csv";

describe("csvCell", () => {
  it("quotes plain values and escapes embedded quotes", () => {
    expect(csvCell("hello")).toBe('"hello"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell(null)).toBe('""');
  });

  it("neutralizes spreadsheet formulas in untrusted text", () => {
    expect(csvCell("=1+1")).toBe("\"'=1+1\"");
    expect(csvCell("+SUM(A1)")).toBe("\"'+SUM(A1)\"");
    expect(csvCell("-2+3")).toBe("\"'-2+3\"");
    expect(csvCell("@cmd")).toBe("\"'@cmd\"");
  });

  it("keeps numbers numeric even when negative", () => {
    expect(csvCell(-5)).toBe('"-5"');
    expect(csvCell(0)).toBe('"0"');
  });

  it("keeps newlines quoted so one record stays on one row", () => {
    expect(csvCell("line1\nline2")).toBe('"line1\nline2"');
  });
});
