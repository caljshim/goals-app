import { isTransferCategory } from "./categories";
import type { Transaction } from "./types";

const P2P = /zelle|venmo/i;

// Money coming IN from a person via Zelle/Venmo — a candidate reimbursement.
export function isIncomingZelle(t: Transaction): boolean {
  return t.category === "TRANSFER_IN" && t.amount < 0 && P2P.test(t.name);
}

// Incoming Zelle the user hasn't resolved yet (not categorized, kept, or linked).
export function pendingIncomingZelle(txns: Transaction[]): Transaction[] {
  return txns.filter(
    (t) => isIncomingZelle(t) && t.user_category === null && t.reimburses_transaction_id === null,
  );
}

// Outgoing Zelle/Venmo awaiting review (money you sent people).
export function pendingOutgoingZelle(txns: Transaction[]): Transaction[] {
  return txns.filter(
    (t) => t.category === "TRANSFER_OUT" && t.user_category === null && t.amount > 0 && P2P.test(t.name),
  );
}

// Real expenses an incoming reimbursement can be linked to: positive (money out),
// not a transfer. Newest first; optional case-insensitive name filter.
export function candidateExpenses(txns: Transaction[], query = ""): Transaction[] {
  const q = query.trim().toLowerCase();
  return txns
    .filter((t) => t.amount > 0 && !isTransferCategory(t.effective_category))
    .filter((t) => !q || (t.merchant_name ?? t.name).toLowerCase().includes(q))
    .sort((a, b) => b.date.localeCompare(a.date));
}

// Incoming reimbursements (within `txns`) that reduce `category` — used to itemize the
// credit inside a budget's breakdown. Covers both a reimbursement linked to an expense
// of that category and one assigned to the category directly. Newest first.
export function reimbursementsForCategory(txns: Transaction[], category: string): Transaction[] {
  const byId = new Map(txns.map((t) => [t.id, t]));
  return txns
    .filter((t) => {
      if (t.reimburses_transaction_id != null) {
        const target = byId.get(t.reimburses_transaction_id);
        return !!target && target.amount >= 0 && target.effective_category === category;
      }
      // category-only: an incoming Zelle assigned straight to this category
      return isIncomingZelle(t) && t.effective_category === category;
    })
    .sort((a, b) => b.date.localeCompare(a.date));
}

// Spending categories present in the data, for a category-only reimbursement.
export function spendingCategories(txns: Transaction[]): string[] {
  return [...new Set(
    txns.map((t) => t.effective_category).filter((c) => !isTransferCategory(c) && c !== "INCOME"),
  )].sort();
}
