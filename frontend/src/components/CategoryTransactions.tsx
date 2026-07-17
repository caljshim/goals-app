import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { isTransferCategory } from "../categories";
import { formatCurrency, prettifyCategory } from "../format";
import type { Transaction } from "../types";

const NEW_CATEGORY = "__new__";

// First day of the month `n` months before today, as YYYY-MM-DD.
function monthsAgoStart(n: number): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

// Repeated charges from the same merchant collapse into one row.
const merchantKey = (t: Transaction) => t.merchant_name ?? t.name;

interface MerchantGroup {
  key: string;
  items: Transaction[];
  total: number;
}
interface Group {
  category: string;
  merchants: MerchantGroup[];
  count: number;
  total: number;
}

export default function CategoryTransactions({ onChange }: { onChange?: () => void }) {
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [newFor, setNewFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Past 3 months = current month + the prior two.
  const start = useMemo(() => monthsAgoStart(2), []);
  const load = () => {
    api.getTransactions({ start })
      .then(setTxns)
      .catch(() => setError("Failed to load transactions. Please try again."));
  };
  useEffect(() => { load(); }, [start]);

  // Transfers/payments move money between accounts, not spending — hide them here.
  const spending = useMemo(
    () => txns.filter((t) => !isTransferCategory(t.effective_category)),
    [txns],
  );

  const groups = useMemo<Group[]>(() => {
    const byCategory = new Map<string, Transaction[]>();
    for (const t of spending) {
      const list = byCategory.get(t.effective_category);
      if (list) list.push(t);
      else byCategory.set(t.effective_category, [t]);
    }
    return [...byCategory.entries()]
      .map(([category, items]) => {
        const byMerchant = new Map<string, Transaction[]>();
        for (const t of items) {
          const k = merchantKey(t);
          const list = byMerchant.get(k);
          if (list) list.push(t);
          else byMerchant.set(k, [t]);
        }
        const merchants = [...byMerchant.entries()]
          .map(([key, mItems]) => ({
            key,
            items: mItems,
            total: mItems.reduce((sum, t) => sum + t.amount, 0),
          }))
          .sort((a, b) => b.total - a.total);
        return {
          category,
          merchants,
          count: items.length,
          total: items.reduce((sum, t) => sum + t.amount, 0),
        };
      })
      .sort((a, b) => b.total - a.total);
  }, [spending]);

  const allCategories = useMemo(
    () => [...new Set(spending.map((t) => t.effective_category))].sort(),
    [spending],
  );

  // Recategorize every transaction in a merchant group in one action.
  const recategorize = async (ids: number[], value: string) => {
    const v = value.trim();
    setNewFor(null);
    if (!v) return;
    try {
      // Serial, not Promise.all: concurrent writes to SQLite can hit "database is locked".
      for (const id of ids) await api.updateTransaction(id, v);
      load();
      onChange?.();
    } catch {
      setError("Failed to update category. Please try again.");
    }
  };

  const toggle = (category: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="font-semibold mb-2">Transactions by category (past 3 months)</h3>
      {error && (
        <div className="mb-3 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="font-medium text-red-700">Dismiss</button>
        </div>
      )}
      {groups.length === 0 && <p className="text-slate-500">No transactions.</p>}

      <div className="divide-y divide-slate-100">
        {groups.map((g) => {
          const open = expanded.has(g.category);
          return (
            <div key={g.category}>
              <button
                onClick={() => toggle(g.category)}
                className="w-full flex items-center justify-between gap-3 py-2 text-left"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="text-slate-400 w-3 shrink-0">{open ? "▾" : "▸"}</span>
                  <span className="font-medium truncate">{prettifyCategory(g.category)}</span>
                  <span className="text-slate-500 text-sm shrink-0">· {g.count} txns</span>
                </span>
                <span className="text-slate-600 text-sm shrink-0">{formatCurrency(g.total)}</span>
              </button>

              {open && (
                <table className="w-full text-sm mb-2">
                  <tbody>
                    {g.merchants.map((mg) => {
                      const rowKey = `${g.category}::${mg.key}`;
                      const ids = mg.items.map((t) => t.id);
                      return (
                        <tr key={rowKey} className="border-t border-slate-50">
                          <td className="py-1 pr-2">
                            {mg.key}
                            {mg.items.length > 1 && (
                              <span className="ml-1.5 text-xs text-slate-500 bg-slate-100 rounded-full px-1.5 py-0.5">
                                ×{mg.items.length}
                              </span>
                            )}
                          </td>
                          <td className="py-1 pr-2 w-52">
                            {newFor === rowKey ? (
                              <input
                                autoFocus
                                placeholder="New category"
                                onBlur={(e) => recategorize(ids, e.currentTarget.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") recategorize(ids, e.currentTarget.value);
                                  if (e.key === "Escape") setNewFor(null);
                                }}
                                className="border rounded px-1 py-0.5 w-full"
                              />
                            ) : (
                              <select
                                value={g.category}
                                onChange={(e) => {
                                  if (e.target.value === NEW_CATEGORY) setNewFor(rowKey);
                                  else recategorize(ids, e.target.value);
                                }}
                                className="border rounded px-1 py-0.5 w-full"
                                title={`Change category for ${mg.items.length} transaction${mg.items.length > 1 ? "s" : ""}`}
                              >
                                {allCategories.map((c) => (
                                  <option key={c} value={c}>{prettifyCategory(c)}</option>
                                ))}
                                <option value={NEW_CATEGORY}>＋ New category…</option>
                              </select>
                            )}
                          </td>
                          <td className={`py-1 text-right whitespace-nowrap ${mg.total < 0 ? "text-emerald-600" : ""}`}>
                            {formatCurrency(mg.total)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
