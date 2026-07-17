// Plaid categories that represent money moving between accounts (or to other
// people) rather than real spending/income. Hidden from the dashboard's spending
// views; still visible on the Transactions page.
// NOTE: keep in sync with backend/app/categories.py TRANSFER_CATEGORIES
export const TRANSFER_CATEGORIES = new Set([
  "LOAN_PAYMENTS",
  "LOAN_DISBURSEMENTS",
  "TRANSFER_IN",
  "TRANSFER_OUT",
]);

export function isTransferCategory(category: string): boolean {
  return TRANSFER_CATEGORIES.has(category);
}
