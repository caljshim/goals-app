import { describe, expect, it } from "vitest";
import { formatCurrency, prettifyCategory } from "./format";

describe("format helpers", () => {
  it("formats currency", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });
  it("prettifies plaid categories", () => {
    expect(prettifyCategory("FOOD_AND_DRINK")).toBe("Food And Drink");
    expect(prettifyCategory("UNCATEGORIZED")).toBe("Uncategorized");
  });
});
