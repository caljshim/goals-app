import { useEffect, useState } from "react";
import { api } from "../api";
import { isTransferCategory } from "../categories";
import { formatCurrency, prettifyCategory } from "../format";
import type { Transaction } from "../types";

// First day of the month `n` months before today, as YYYY-MM-DD.
function monthsAgoStart(n: number): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

const P2P = /zelle|venmo/i;

/**
 * Floating prompt for outgoing Zelle/Venmo payments that haven't been reviewed.
 * Picking a category turns the payment into real category spending; "keep" stamps
 * user_category=TRANSFER_OUT so it stays netted as a transfer and stops appearing.
 */
export default function P2PReviewCard({
  refreshSignal,
  onChange,
}: {
  refreshSignal: number;
  onChange?: () => void;
}) {
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);

  const load = () =>
    api.getTransactions({ start: monthsAgoStart(2) }).then(setTxns).catch(() => {});
  useEffect(() => { load(); }, [refreshSignal]);

  const queue = txns.filter(
    (t) => t.category === "TRANSFER_OUT" && t.user_category === null && t.amount > 0 && P2P.test(t.name),
  );
  const categories = [...new Set(
    txns.map((t) => t.effective_category).filter((c) => !isTransferCategory(c) && c !== "INCOME"),
  )].sort();

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

  const keepAll = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // serial: concurrent SQLite writes can hit "database is locked"
      for (const t of queue) await api.updateTransaction(t.id, "TRANSFER_OUT");
      await load();
      onChange?.();
    } finally {
      setBusy(false);
    }
  };

  if (hidden || queue.length === 0) return null;

  return (
    <div className="fixed bottom-4 left-4 z-50 w-[26rem] max-w-[calc(100vw-2rem)] bg-white rounded-xl border border-slate-300 shadow-lg">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200">
        <span className="font-semibold text-sm">
          💸 Categorize {queue.length} Zelle/Venmo payment{queue.length > 1 ? "s" : ""}?
        </span>
        <button onClick={() => setHidden(true)} title="Hide until next visit"
          className="text-slate-400 hover:text-slate-600 text-sm">✕</button>
      </div>

      <div className="max-h-72 overflow-y-auto p-3 space-y-2">
        <p className="text-xs text-slate-500">
          Money you sent people — was it really spending (rent share, dinner…)? Pick a
          category to count it in your budget, or keep it as a plain transfer.
        </p>
        {queue.map((t) => (
          <div key={t.id} className="flex items-center gap-2 text-xs border border-slate-100 rounded-lg px-2 py-1.5">
            <div className="min-w-0 flex-1">
              <div className="truncate text-slate-700">{t.name}</div>
              <div className="text-slate-400">{t.date} · {formatCurrency(t.amount)}</div>
            </div>
            <select
              defaultValue=""
              disabled={busy}
              onChange={(e) => { if (e.target.value) resolve(t.id, e.target.value); }}
              className="border rounded px-1 py-1 w-36 shrink-0"
            >
              <option value="" disabled>Category…</option>
              {categories.map((c) => (
                <option key={c} value={c}>{prettifyCategory(c)}</option>
              ))}
            </select>
            <button onClick={() => resolve(t.id, "TRANSFER_OUT")} disabled={busy}
              title="Not spending — keep as a transfer"
              className="text-slate-500 hover:text-slate-700 shrink-0">Keep</button>
          </div>
        ))}
      </div>

      <div className="px-4 py-2 border-t border-slate-200 text-right">
        <button onClick={keepAll} disabled={busy}
          className="text-xs text-slate-500 hover:text-slate-700">
          {busy ? "Saving…" : "Keep all as transfers"}
        </button>
      </div>
    </div>
  );
}
