import { describe, expect, it } from "vitest";
import { formatCurrency, formatDateFull, prettifyCategory } from "./format";

describe("format helpers", () => {
  it("formats currency", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });
  it("formats an ISO date as American M/D/YYYY (no timezone drift)", () => {
    expect(formatDateFull("2026-07-15")).toBe("7/15/2026");
    expect(formatDateFull("2026-01-05")).toBe("1/5/2026");
  });
  it("prettifies plaid categories", () => {
    expect(prettifyCategory("FOOD_AND_DRINK")).toBe("Food And Drink");
    expect(prettifyCategory("UNCATEGORIZED")).toBe("Uncategorized");
  });
});
