import { describe, expect, it } from "vitest";
import { unbudgetedTransactions } from "./unbudgeted";
import type { Transaction } from "./types";

function transaction(id: number, date: string, isBudgeted: boolean | null): Transaction {
  return {
    id, date, is_budgeted: isBudgeted, account_id: 1, name: `Transaction ${id}`,
    merchant_name: null, amount: 10, category: "SHOPPING", user_category: null,
    effective_category: "SHOPPING", pending: false, is_manual: false,
    reimburses_transaction_id: null,
  };
}

describe("unbudgetedTransactions", () => {
  it("returns only unbudgeted spending in the requested month", () => {
    const rows = [
      transaction(1, "2026-07-02", false),
      transaction(2, "2026-07-03", true),
      transaction(3, "2026-07-04", null),
      transaction(4, "2026-06-30", false),
    ];
    expect(unbudgetedTransactions(rows, "2026-07").map((row) => row.id)).toEqual([1]);
  });
});
