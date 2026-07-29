import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import { pendingIncomingZelle, pendingOutgoingZelle, spendingCategories } from "../zelle";
import type { Transaction } from "../types";
import ExpensePicker from "./ExpensePicker";

// First day of the month `n` months before today, as YYYY-MM-DD.
function monthsAgoStart(n: number): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

/**
 * Floating prompt for Zelle/Venmo payments that haven't been reviewed.
 *  - Sent (money out): pick a category to count it as spending, or keep as a transfer.
 *  - Received (money in): link it to the expense it reimburses (reducing that budget),
 *    assign a category, or keep it as a plain transfer.
 */
export default function P2PReviewCard({
  refreshSignal = 0,
  onChange,
  embedded = false,
}: {
  refreshSignal?: number;
  onChange?: () => void;
  embedded?: boolean;
}) {
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedCategory, setSelectedCategory] = useState("");
  const [bulkLinking, setBulkLinking] = useState(false);

  const load = () =>
    api.getTransactions({ start: monthsAgoStart(2) }).then(setTxns).catch(() => {});
  useEffect(() => { load(); }, [refreshSignal]);

  const incoming = pendingIncomingZelle(txns);
  const outgoing = pendingOutgoingZelle(txns);
  const pending = [...incoming, ...outgoing];
  const selected = pending.filter((transaction) => selectedIds.has(transaction.id));
  const selectedIncoming = selected.filter((transaction) => incoming.some((row) => row.id === transaction.id));
  const selectedOutgoing = selected.filter((transaction) => outgoing.some((row) => row.id === transaction.id));
  const categories = spendingCategories(txns);

  const finishBulkChange = async () => {
    setSelectedIds(new Set());
    setSelectedCategory("");
    setBulkLinking(false);
    await load();
    onChange?.();
  };

  const resolveSelected = async (category: string) => {
    if (busy || selected.length === 0) return;
    setBusy(true);
    try {
      await api.bulkUpdateTransactions(selected.map((transaction) => transaction.id), category);
      await finishBulkChange();
    } finally {
      setBusy(false);
    }
  };

  const linkSelected = async (targetId: number) => {
    if (busy || selectedIncoming.length === 0) return;
    setBusy(true);
    try {
      await api.bulkLinkReimbursements(
        selectedIncoming.map((transaction) => transaction.id),
        targetId,
      );
      await finishBulkChange();
    } finally {
      setBusy(false);
    }
  };

  const keepSelectedAsTransfers = async () => {
    if (busy || selected.length === 0) return;
    setBusy(true);
    try {
      if (selectedOutgoing.length) {
        await api.bulkUpdateTransactions(selectedOutgoing.map((transaction) => transaction.id), "TRANSFER_OUT");
      }
      if (selectedIncoming.length) {
        await api.bulkUpdateTransactions(selectedIncoming.map((transaction) => transaction.id), "TRANSFER_IN");
      }
      await finishBulkChange();
    } finally {
      setBusy(false);
    }
  };

  const toggleSelected = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (hidden && !embedded) return null;
  if (incoming.length === 0 && outgoing.length === 0) {
    if (!embedded) return null;
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="font-semibold">Zelle & Venmo review</h3>
        <p className="mt-1 text-sm text-slate-500">All peer payments have been reviewed.</p>
      </div>
    );
  }
  const total = incoming.length + outgoing.length;

  return (
    <div className={embedded
      ? "w-full rounded-xl border border-slate-200 bg-white"
      : "fixed bottom-4 left-4 z-50 w-[26rem] max-w-[calc(100vw-2rem)] rounded-xl border border-slate-300 bg-white shadow-lg"}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200">
        <span className="font-semibold text-sm">
          💸 Review {total} Zelle/Venmo payment{total > 1 ? "s" : ""}
        </span>
        {!embedded && (
          <button onClick={() => setHidden(true)} title="Hide until next visit"
            className="text-sm text-slate-400 hover:text-slate-600">✕</button>
        )}
      </div>

      <div className="max-h-80 overflow-y-auto p-3 space-y-3">
        {incoming.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-slate-600">Received — reimburse an expense</p>
            <p className="text-xs text-slate-500">
              Link it to the exact expense, apply it to a budget, or mark it as not a
              reimbursement so it does not change spending.
            </p>
            {incoming.map((t) => (
              <button key={t.id} type="button" onClick={() => toggleSelected(t.id)} disabled={busy}
                className={`w-full text-left text-xs rounded-lg border px-2 py-1.5 ${
                  selectedIds.has(t.id) ? "border-emerald-400 bg-emerald-50" : "border-slate-100"
                }`}>
                <div className="flex items-start gap-2">
                  <span className={selectedIds.has(t.id) ? "text-emerald-600" : "text-slate-300"}>
                    {selectedIds.has(t.id) ? "●" : "○"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-slate-700">{t.name}</div>
                    <div className="text-emerald-600">{formatDateFull(t.date)} · {formatCurrency(t.amount)}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {outgoing.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-slate-600">Sent — was it spending?</p>
            <p className="text-xs text-slate-500">
              Choose a category if this was spending, or mark it as not spending so it stays
              out of spending totals.
            </p>
            {outgoing.map((t) => (
              <button key={t.id} type="button" onClick={() => toggleSelected(t.id)} disabled={busy}
                className={`w-full rounded-lg border px-2 py-1.5 text-left text-xs ${
                  selectedIds.has(t.id) ? "border-emerald-400 bg-emerald-50" : "border-slate-100"
                }`}>
                <div className="flex items-start gap-2">
                  <span className={selectedIds.has(t.id) ? "text-emerald-600" : "text-slate-300"}>
                    {selectedIds.has(t.id) ? "●" : "○"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-slate-700">{t.name}</div>
                    <div className="text-slate-400">{formatDateFull(t.date)} · {formatCurrency(t.amount)}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-slate-200 px-4 py-2">
        <div className="flex items-center justify-between text-xs">
          <button onClick={() => setSelectedIds(
            selected.length === pending.length ? new Set() : new Set(pending.map((transaction) => transaction.id)),
          )} disabled={busy} className="font-medium text-slate-600 hover:text-slate-900">
            {selected.length === pending.length ? "Clear selection" : "Select all"}
          </button>
          <span className="text-slate-400">{selected.length} selected</span>
        </div>
        {selected.length > 0 && (
          <>
            <div className="flex items-center gap-2">
              <select value={selectedCategory} disabled={busy}
                onChange={(event) => setSelectedCategory(event.target.value)}
                className="min-w-0 flex-1 rounded border px-2 py-1 text-xs">
                <option value="">Choose category…</option>
                {categories.map((category) => (
                  <option key={category} value={category}>{prettifyCategory(category)}</option>
                ))}
              </select>
              <button onClick={() => resolveSelected(selectedCategory)}
                disabled={busy || !selectedCategory}
                className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-40">
                Apply
              </button>
              {selectedIncoming.length === selected.length && (
                <button onClick={() => setBulkLinking((open) => !open)} disabled={busy}
                  className="whitespace-nowrap text-xs font-medium text-slate-600 hover:text-slate-900">
                  Link expense
                </button>
              )}
            </div>
            <button onClick={keepSelectedAsTransfers} disabled={busy}
              className="text-xs text-slate-500 hover:text-slate-700">
              {busy ? "Saving…" : "Mark selected as transfers"}
            </button>
            {bulkLinking && selectedIncoming.length === selected.length && (
              <ExpensePicker
                expenses={txns}
                onPick={linkSelected}
                onCancel={() => setBulkLinking(false)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
