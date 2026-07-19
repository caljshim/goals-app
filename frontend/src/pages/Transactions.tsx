import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import ExpensePicker from "../components/ExpensePicker";
import MerchantRules from "../components/MerchantRules";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import { filterTransactions } from "../search";
import { isIncomingZelle } from "../zelle";
import type { Account, Transaction } from "../types";

export default function Transactions() {
  const [rows, setRows] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ account_id: 0, date: "", name: "", amount: "" });
  const [error, setError] = useState<string | null>(null);
  const [linkingId, setLinkingId] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [rulesSignal, setRulesSignal] = useState(0);

  // Load once; search filters client-side (no per-keystroke API calls).
  const load = () => {
    api.getTransactions()
      .then(setRows)
      .catch(() => setError("Failed to load transactions. Please try again."));
  };
  useEffect(() => { api.getAccounts().then(setAccounts); }, []);
  useEffect(() => { load(); }, []);

  const visible = filterTransactions(rows, query);

  const draftFor = (t: Transaction) => drafts[t.id] ?? t.effective_category;
  const setDraft = (id: number, v: string) => setDrafts((d) => ({ ...d, [id]: v }));
  const clearDraft = (id: number) =>
    setDrafts((d) => { const n = { ...d }; delete n[id]; return n; });

  // Rule by default: make the category stick for the whole merchant (past & future).
  const applyRule = async (t: Transaction) => {
    const v = draftFor(t).trim();
    if (!v || v === t.effective_category) { clearDraft(t.id); return; }
    try {
      await api.setMerchantCategory(t.id, v);
      clearDraft(t.id); load(); setRulesSignal((s) => s + 1);
    } catch {
      setError("Failed to apply category rule. Please try again.");
    }
  };

  // One-off exception on just this transaction (overrides its merchant rule).
  const applyOneOff = async (t: Transaction) => {
    const v = draftFor(t).trim();
    if (!v) return;
    try {
      await api.updateTransaction(t.id, v);
      clearDraft(t.id); load();
    } catch {
      setError("Failed to update category. Please try again.");
    }
  };

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createTransaction({
        account_id: Number(form.account_id), date: form.date,
        name: form.name, amount: Number(form.amount),
      });
      setForm({ account_id: 0, date: "", name: "", amount: "" });
      load();
    } catch {
      setError("Failed to add transaction. Please try again.");
    }
  };

  const removeTransaction = async (id: number) => {
    try {
      await api.deleteTransaction(id);
      load();
    } catch {
      setError("Failed to delete transaction. Please try again.");
    }
  };

  const unlinkReimbursement = async (id: number) => {
    try {
      await api.linkReimbursement(id, null);
      load();
    } catch {
      setError("Failed to unlink reimbursement. Please try again.");
    }
  };

  const linkReimbursement = async (id: number, targetId: number) => {
    try {
      await api.linkReimbursement(id, targetId);
      setLinkingId(null);
      load();
    } catch {
      setError("Failed to link reimbursement. Please try again.");
    }
  };

  return (
    <div>
      {error && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="font-medium text-red-700">Dismiss</button>
        </div>
      )}
      <form onSubmit={addManual} className="flex flex-wrap gap-2 mb-4 bg-white p-3 rounded-xl border border-slate-200">
        <select required value={form.account_id} onChange={(e) => setForm({ ...form, account_id: Number(e.target.value) })}
          className="border rounded px-2 py-1">
          <option value={0} disabled>Account</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
          className="border rounded px-2 py-1" />
        <input required placeholder="Description" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} className="border rounded px-2 py-1" />
        <input required type="number" step="0.01" placeholder="Amount (+ spent / − income)"
          value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })}
          className="border rounded px-2 py-1 w-52" />
        <button className="px-3 py-1 rounded bg-slate-900 text-white text-sm">Add</button>
      </form>

      <MerchantRules signal={rulesSignal} onChange={load} />

      <div className="flex items-center gap-2 mb-3">
        <input placeholder="Search merchant, description, or category…" value={query}
          onChange={(e) => setQuery(e.target.value)} className="border rounded px-2 py-1 w-80" />
        {query && (
          <span className="text-xs text-slate-500">
            {visible.length} of {rows.length}
            <button onClick={() => setQuery("")} className="ml-2 text-slate-400 hover:text-slate-600">clear</button>
          </span>
        )}
      </div>

      <table className="w-full text-sm bg-white rounded-xl border border-slate-200 overflow-hidden">
        <thead className="bg-slate-100 text-left">
          <tr><th className="p-2">Date</th><th className="p-2">Name</th><th className="p-2">Category</th>
          <th className="p-2 text-right">Amount</th><th className="p-2"></th></tr>
        </thead>
        <tbody>
          {visible.map((t) => {
            const linked = t.reimburses_transaction_id !== null;
            const showReimburse = isIncomingZelle(t) || linked;
            return (
              <Fragment key={t.id}>
                <tr className="border-t border-slate-100">
                  <td className="p-2 align-top whitespace-nowrap">{formatDateFull(t.date)}</td>
                  <td className="p-2 align-top">
                    {t.merchant_name ?? t.name}
                    {showReimburse && (
                      <div className="text-xs mt-0.5">
                        {linked ? (
                          <span className="text-emerald-700">
                            ↩ reimburses {rows.find((r) => r.id === t.reimburses_transaction_id)?.name ?? "an expense"}
                            <button onClick={() => setLinkingId(linkingId === t.id ? null : t.id)}
                              className="ml-1.5 text-slate-500 hover:text-slate-700">change</button>
                            <button onClick={() => unlinkReimbursement(t.id)}
                              className="ml-1.5 text-slate-400 hover:text-slate-600">unlink</button>
                          </span>
                        ) : t.effective_category !== "TRANSFER_IN" ? (
                          <span className="text-emerald-700">
                            ↩ reduces {prettifyCategory(t.effective_category)}
                            <button onClick={() => setLinkingId(linkingId === t.id ? null : t.id)}
                              className="ml-1.5 text-slate-500 hover:text-slate-700">
                              {linkingId === t.id ? "close" : "link to an expense"}
                            </button>
                          </span>
                        ) : (
                          <button onClick={() => setLinkingId(linkingId === t.id ? null : t.id)}
                            className="text-slate-500 hover:text-slate-700">
                            {linkingId === t.id ? "Close" : "↩ Link to an expense"}
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="p-2 align-top">
                    <input value={draftFor(t)} onChange={(e) => setDraft(t.id, e.currentTarget.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") applyRule(t); }}
                      className="border rounded px-1 py-0.5 w-40"
                      title="Enter (or ‘apply to merchant’) saves a rule for this merchant" />
                    {draftFor(t).trim() && draftFor(t) !== t.effective_category && (
                      <div className="text-[11px] mt-0.5 flex gap-2">
                        <button onClick={() => applyRule(t)} className="text-sky-600 hover:text-sky-800">
                          apply to {(t.merchant_name ?? t.name).slice(0, 18)}
                        </button>
                        <button onClick={() => applyOneOff(t)} className="text-slate-400 hover:text-slate-600">
                          just this one
                        </button>
                      </div>
                    )}
                  </td>
                  <td className={`p-2 text-right align-top ${t.amount < 0 ? "text-emerald-600" : ""}`}>
                    {formatCurrency(t.amount)}
                  </td>
                  <td className="p-2 text-right align-top">
                    {t.is_manual && (
                      <button onClick={() => removeTransaction(t.id)}
                        className="text-red-500 text-xs">Delete</button>
                    )}
                  </td>
                </tr>
                {linkingId === t.id && (
                  <tr className="border-t border-slate-50">
                    <td colSpan={5} className="p-2 bg-slate-50">
                      <div className="max-w-md">
                        <ExpensePicker
                          expenses={rows}
                          onPick={(eid) => linkReimbursement(t.id, eid)}
                          onCancel={() => setLinkingId(null)}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {visible.length === 0 && (
            <tr><td colSpan={5} className="p-4 text-slate-500">
              {rows.length === 0 ? "No transactions." : "No transactions match your search."}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
