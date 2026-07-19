import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import { localMonthKey, unbudgetedTransactions } from "../unbudgeted";
import type { Transaction } from "../types";

const EXPANDED_STORAGE_KEY = "money.ui.unbudgetedTransactions.expanded";

export default function UnbudgetedTransactionsNotice({
  transactions,
  onOpenTransactions,
  onCategorized,
}: {
  transactions: Transaction[];
  onOpenTransactions?: () => void;
  onCategorized?: () => void | Promise<void>;
}) {
  const [expanded, setExpanded] = useState(
    () => localStorage.getItem(EXPANDED_STORAGE_KEY) === "true",
  );
  const [editingId, setEditingId] = useState<number | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [resolvedIds, setResolvedIds] = useState<Set<number>>(new Set());
  const [budgetCategories, setBudgetCategories] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const rows = unbudgetedTransactions(transactions, localMonthKey())
    .filter((transaction) => !resolvedIds.has(transaction.id));

  useEffect(() => {
    if (!expanded) return;
    api.getBudgets()
      .then((budgets) => setBudgetCategories(
        [...new Set(budgets.map((budget) => budget.category))].sort(),
      ))
      .catch(() => setBudgetCategories([]));
  }, [expanded]);

  if (rows.length === 0) return null;

  const categories = [...new Set(rows.map((row) => row.effective_category))].sort();
  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    localStorage.setItem(EXPANDED_STORAGE_KEY, String(next));
  };
  const categorize = async (transaction: Transaction, category: string) => {
    if (!category || savingId !== null) return;
    setSavingId(transaction.id);
    setSaveError(null);
    try {
      await api.updateTransaction(transaction.id, category);
      setResolvedIds((current) => new Set(current).add(transaction.id));
      setEditingId(null);
      await onCategorized?.();
    } catch {
      setSaveError("Could not update that transaction. Please try again.");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="mb-3 rounded-xl border border-amber-400 border-l-4 bg-amber-100 px-3 py-3 text-sm text-amber-950 shadow-sm">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-2 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block font-medium">
            ⚠ {rows.length} unbudgeted transaction{rows.length === 1 ? "" : "s"} this month
          </span>
          <span className="mt-0.5 block text-xs text-amber-800">
            These still count toward spending, but their categories have no monthly budget:
            {" "}{categories.map(prettifyCategory).join(", ")}.
          </span>
        </span>
        <span aria-hidden="true" className="mt-0.5 shrink-0 text-amber-700">
          {expanded ? "▴" : "▾"}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 max-h-64 divide-y divide-amber-200 overflow-y-auto border-t border-amber-200">
          {rows.map((transaction) => (
            <div key={transaction.id} className="py-2">
              <button
                type="button"
                onClick={() => setEditingId(editingId === transaction.id ? null : transaction.id)}
                aria-expanded={editingId === transaction.id}
                className="flex w-full items-start justify-between gap-3 text-left"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium text-amber-950">
                    {transaction.merchant_name ?? transaction.name}
                  </div>
                  <div className="text-xs text-amber-800">
                    {formatDateFull(transaction.date)} · {prettifyCategory(transaction.effective_category)}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="font-medium tabular-nums">{formatCurrency(transaction.amount)}</span>
                  <span aria-hidden="true" className="text-amber-700">›</span>
                </div>
              </button>
              {editingId === transaction.id && (
                <div className="mt-2 rounded-lg border border-amber-300 bg-white/70 p-2">
                  <label className="block text-xs font-medium text-amber-950">
                    Count this transaction under
                    <select
                      defaultValue=""
                      disabled={savingId !== null}
                      onChange={(event) => categorize(transaction, event.target.value)}
                      className="mt-1 block w-full rounded-md border border-amber-300 bg-white px-2 py-1.5 text-sm"
                    >
                      <option value="" disabled>Choose a budget category…</option>
                      {budgetCategories.map((category) => (
                        <option key={category} value={category}>{prettifyCategory(category)}</option>
                      ))}
                    </select>
                  </label>
                  {budgetCategories.length === 0 && (
                    <p className="mt-1 text-xs text-amber-800">Create a budget before assigning this transaction to one.</p>
                  )}
                  <p className="mt-1 text-[11px] text-amber-700">This changes only this transaction.</p>
                </div>
              )}
            </div>
          ))}
          {saveError && <p className="py-2 text-xs font-medium text-red-700">{saveError}</p>}
        </div>
      )}
      {onOpenTransactions && (
        <button
          type="button"
          onClick={onOpenTransactions}
          className="mt-2 whitespace-nowrap rounded-lg bg-amber-950 px-3 py-1.5 text-xs font-semibold text-white"
        >
          Open Transactions
        </button>
      )}
    </div>
  );
}
