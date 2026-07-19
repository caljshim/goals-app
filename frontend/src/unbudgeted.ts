import type { Transaction } from "./types";

export function unbudgetedTransactions(
  transactions: Transaction[],
  month: string,
): Transaction[] {
  return transactions.filter(
    (transaction) => transaction.date.startsWith(month) && transaction.is_budgeted === false,
  );
}

export function localMonthKey(date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
