import { describe, expect, it } from "vitest";
import { candidateExpenses, isIncomingZelle, pendingIncomingZelle, reimbursementsForCategory, spendingCategories } from "./zelle";
import type { Transaction } from "./types";

function tx(p: Partial<Transaction>): Transaction {
  return {
    id: 1, account_id: 1, date: "2026-07-01", name: "x", merchant_name: null,
    amount: 10, category: null, user_category: null, effective_category: "UNCATEGORIZED",
    pending: false, is_manual: false, reimburses_transaction_id: null, ...p,
  };
}

describe("zelle helpers", () => {
  it("detects an incoming Zelle (money in via a person)", () => {
    expect(isIncomingZelle(tx({ category: "TRANSFER_IN", amount: -60, name: "Zelle payment from Ryan" }))).toBe(true);
    expect(isIncomingZelle(tx({ category: "TRANSFER_OUT", amount: 60, name: "Venmo" }))).toBe(false);
    expect(isIncomingZelle(tx({ category: "TRANSFER_IN", amount: -60, name: "Online Transfer from CHK" }))).toBe(false);
  });

  it("queues only unreviewed incoming Zelle", () => {
    const list = [
      tx({ id: 1, category: "TRANSFER_IN", amount: -60, name: "Zelle from A" }),
      tx({ id: 2, category: "TRANSFER_IN", amount: -60, name: "Zelle from B", user_category: "FOOD_AND_DRINK" }),
      tx({ id: 3, category: "TRANSFER_IN", amount: -60, name: "Zelle from C", reimburses_transaction_id: 9 }),
      tx({ id: 4, category: "TRANSFER_IN", amount: -60, name: "Zelle from D", user_category: "TRANSFER_IN" }),
    ];
    expect(pendingIncomingZelle(list).map((t) => t.id)).toEqual([1]);
  });

  it("lists candidate expenses (positive, non-transfer), newest first, filtered", () => {
    const list = [
      tx({ id: 1, amount: 180, name: "Group dinner", date: "2026-07-12", effective_category: "FOOD_AND_DRINK" }),
      tx({ id: 2, amount: -2000, name: "Paycheck", effective_category: "INCOME" }),
      tx({ id: 3, amount: 45, name: "Transfer to savings", effective_category: "TRANSFER_OUT" }),
      tx({ id: 4, amount: 30, name: "Movie", date: "2026-07-15", effective_category: "ENTERTAINMENT" }),
    ];
    expect(candidateExpenses(list).map((t) => t.id)).toEqual([4, 1]);
    expect(candidateExpenses(list, "dinner").map((t) => t.id)).toEqual([1]);
  });

  it("finds reimbursements (linked and category-only) for a category, newest first", () => {
    const list = [
      tx({ id: 10, amount: 180, effective_category: "FOOD_AND_DRINK", date: "2026-07-12" }),
      tx({ id: 11, amount: 30, effective_category: "ENTERTAINMENT", date: "2026-07-15" }),
      tx({ id: 20, amount: -60, category: "TRANSFER_IN", name: "Zelle from Ryan", date: "2026-07-14", reimburses_transaction_id: 10 }),
      tx({ id: 21, amount: -40, category: "TRANSFER_IN", name: "Zelle from Mom", date: "2026-07-20", reimburses_transaction_id: 10 }),
      tx({ id: 22, amount: -10, category: "TRANSFER_IN", name: "Zelle for movie", date: "2026-07-16", reimburses_transaction_id: 11 }),
      // category-only reimbursement assigned directly to FOOD_AND_DRINK
      tx({ id: 30, amount: -25, category: "TRANSFER_IN", name: "Zelle from Sam", date: "2026-07-18", user_category: "FOOD_AND_DRINK", effective_category: "FOOD_AND_DRINK" }),
      // kept transfer — not a reimbursement to any category
      tx({ id: 23, amount: -99, category: "TRANSFER_IN", name: "kept", date: "2026-07-01", user_category: "TRANSFER_IN", effective_category: "TRANSFER_IN" }),
    ];
    // linked (targets 10) + category-only (30); movie's (11) excluded; newest first
    expect(reimbursementsForCategory(list, "FOOD_AND_DRINK").map((t) => t.id)).toEqual([21, 30, 20]);
  });

  it("offers spending categories for a category-only reimbursement", () => {
    const list = [
      tx({ effective_category: "FOOD_AND_DRINK" }),
      tx({ effective_category: "ENTERTAINMENT" }),
      tx({ effective_category: "TRANSFER_IN" }),
      tx({ effective_category: "INCOME" }),
    ];
    expect(spendingCategories(list)).toEqual(["ENTERTAINMENT", "FOOD_AND_DRINK"]);
  });
});
