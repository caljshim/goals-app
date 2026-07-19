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
  const [linkingId, setLinkingId] = useState<number | null>(null);

  const load = () =>
    api.getTransactions({ start: monthsAgoStart(2) }).then(setTxns).catch(() => {});
  useEffect(() => { load(); }, [refreshSignal]);

  const incoming = pendingIncomingZelle(txns);
  const outgoing = pendingOutgoingZelle(txns);
  const categories = spendingCategories(txns);

  // Set user_category (a spending bucket, or TRANSFER_IN/OUT to keep as a transfer).
  const resolve = async (id: number, category: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.updateTransaction(id, category);
      await load();
      onChange?.();
    } finally {
      setBusy(false);
    }
  };

  const link = async (id: number, targetId: number) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.linkReimbursement(id, targetId);
      setLinkingId(null);
      await load();
      onChange?.();
    } finally {
      setBusy(false);
    }
  };

  const keepAll = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // serial: concurrent SQLite writes can hit "database is locked"
      for (const t of outgoing) await api.updateTransaction(t.id, "TRANSFER_OUT");
      for (const t of incoming) await api.updateTransaction(t.id, "TRANSFER_IN");
      await load();
      onChange?.();
    } finally {
      setBusy(false);
    }
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
              <div key={t.id} className="text-xs border border-slate-100 rounded-lg px-2 py-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-slate-700">{t.name}</div>
                    <div className="text-emerald-600">{formatDateFull(t.date)} · {formatCurrency(t.amount)}</div>
                  </div>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => setLinkingId(linkingId === t.id ? null : t.id)}
                    disabled={busy}
                    className="shrink-0 whitespace-nowrap text-slate-600 hover:text-slate-900"
                  >
                    {linkingId === t.id ? "Close" : "Link expense"}
                  </button>
                  <select
                    defaultValue=""
                    disabled={busy}
                    onChange={(e) => { if (e.target.value) resolve(t.id, e.target.value); }}
                    className="w-32 shrink-0 rounded border px-1 py-1"
                    title="Apply this reimbursement to a budget category"
                  >
                    <option value="" disabled>Choose budget…</option>
                    {categories.map((c) => <option key={c} value={c}>{prettifyCategory(c)}</option>)}
                  </select>
                  <button onClick={() => resolve(t.id, "TRANSFER_IN")} disabled={busy}
                    title="Exclude this payment from spending and budget calculations"
                    className="shrink-0 whitespace-nowrap text-slate-500 hover:text-slate-700">
                    Not a reimbursement
                  </button>
                </div>
                {linkingId === t.id && (
                  <ExpensePicker
                    expenses={txns}
                    onPick={(eid) => link(t.id, eid)}
                    onCancel={() => setLinkingId(null)}
                  />
                )}
              </div>
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
              <div key={t.id} className="rounded-lg border border-slate-100 px-2 py-1.5 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-slate-700">{t.name}</div>
                    <div className="text-slate-400">{formatDateFull(t.date)} · {formatCurrency(t.amount)}</div>
                  </div>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <select
                    defaultValue=""
                    disabled={busy}
                    onChange={(e) => { if (e.target.value) resolve(t.id, e.target.value); }}
                    className="w-40 shrink-0 rounded border px-1 py-1"
                  >
                    <option value="" disabled>Choose category…</option>
                    {categories.map((c) => (
                      <option key={c} value={c}>{prettifyCategory(c)}</option>
                    ))}
                  </select>
                  <button onClick={() => resolve(t.id, "TRANSFER_OUT")} disabled={busy}
                    title="Exclude this payment from spending and budget calculations"
                    className="shrink-0 whitespace-nowrap text-slate-500 hover:text-slate-700">
                    Not spending
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="px-4 py-2 border-t border-slate-200 text-right">
        <button onClick={keepAll} disabled={busy}
          className="text-xs text-slate-500 hover:text-slate-700">
          {busy ? "Saving…" : "Mark all reviewed — no spending changes"}
        </button>
      </div>
    </div>
  );
}
