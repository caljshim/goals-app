import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency } from "../format";
import type { Account, Transaction } from "../types";

export default function Transactions() {
  const [rows, setRows] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [category, setCategory] = useState("");
  const [form, setForm] = useState({ account_id: 0, date: "", name: "", amount: "" });
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    const params: Record<string, string> = {};
    if (category) params.category = category;
    api.getTransactions(params)
      .then(setRows)
      .catch(() => setError("Failed to load transactions. Please try again."));
  };
  useEffect(() => { api.getAccounts().then(setAccounts); }, []);
  useEffect(() => { load(); }, [category]);

  const recategorize = async (id: number, value: string) => {
    try {
      await api.updateTransaction(id, value || null);
      load();
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

      <input placeholder="Filter by category (e.g. GROCERIES)" value={category}
        onChange={(e) => setCategory(e.target.value)} className="border rounded px-2 py-1 mb-3 w-72" />

      <table className="w-full text-sm bg-white rounded-xl border border-slate-200 overflow-hidden">
        <thead className="bg-slate-100 text-left">
          <tr><th className="p-2">Date</th><th className="p-2">Name</th><th className="p-2">Category</th>
          <th className="p-2 text-right">Amount</th><th className="p-2"></th></tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className="border-t border-slate-100">
              <td className="p-2">{t.date}</td>
              <td className="p-2">{t.merchant_name ?? t.name}</td>
              <td className="p-2">
                <input defaultValue={t.effective_category} onBlur={(e) => recategorize(t.id, e.currentTarget.value)}
                  className="border rounded px-1 py-0.5 w-40" title="Edit to recategorize" />
              </td>
              <td className={`p-2 text-right ${t.amount < 0 ? "text-emerald-600" : ""}`}>
                {formatCurrency(t.amount)}
              </td>
              <td className="p-2 text-right">
                {t.is_manual && (
                  <button onClick={() => removeTransaction(t.id)}
                    className="text-red-500 text-xs">Delete</button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">No transactions.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
