import { describe, expect, it } from "vitest";
import { filterTransactions } from "./search";
import type { Transaction } from "./types";

function tx(p: Partial<Transaction>): Transaction {
  return {
    id: 1, account_id: 1, date: "2026-07-01", name: "x", merchant_name: null,
    amount: 10, category: null, user_category: null, effective_category: "UNCATEGORIZED",
    pending: false, is_manual: false, reimburses_transaction_id: null, ...p,
  };
}

const rows = [
  tx({ id: 1, merchant_name: "Safeway", name: "SAFEWAY #123", effective_category: "GROCERIES", date: "2026-07-15" }),
  tx({ id: 2, merchant_name: "Blue Bottle Coffee", name: "BLUE BOTTLE", effective_category: "FOOD_AND_DRINK", date: "2026-06-02" }),
  tx({ id: 3, merchant_name: null, name: "Chevron", effective_category: "RENT_AND_UTILITIES", date: "2026-07-15" }),
];

describe("transaction search", () => {
  it("returns everything for an empty/whitespace query", () => {
    expect(filterTransactions(rows, "").length).toBe(3);
    expect(filterTransactions(rows, "   ").length).toBe(3);
  });
  it("matches merchant name (case-insensitive substring)", () => {
    expect(filterTransactions(rows, "safe").map((t) => t.id)).toEqual([1]);
  });
  it("matches the description", () => {
    expect(filterTransactions(rows, "bottle").map((t) => t.id)).toEqual([2]);
  });
  it("matches category, raw or prettified and partial", () => {
    expect(filterTransactions(rows, "groc").map((t) => t.id)).toEqual([1]);
    expect(filterTransactions(rows, "food and").map((t) => t.id)).toEqual([2]);
  });
  it("matches the date", () => {
    expect(filterTransactions(rows, "2026-07-15").map((t) => t.id)).toEqual([1, 3]);
  });
  it("requires all whitespace-separated terms (AND)", () => {
    expect(filterTransactions(rows, "safeway groceries").map((t) => t.id)).toEqual([1]);
    expect(filterTransactions(rows, "safeway coffee").length).toBe(0);
  });
});
