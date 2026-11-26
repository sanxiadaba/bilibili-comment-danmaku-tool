const FORMULA_PREFIX = /^[=+\-@\t\r]/;

/**
 * Quote one CSV cell and neutralize spreadsheet formulas (comments are untrusted remote text).
 * Only text is prefixed: a numeric cell such as -5 must stay a number.
 */
export function csvCell(value: unknown) {
  let text = value === null || value === undefined ? "" : String(value);
  if (typeof value === "string" && FORMULA_PREFIX.test(text)) {
    text = `'${text}`;
  }
  return `"${text.replace(/"/g, '""')}"`;
}
