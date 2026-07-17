import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency, prettifyCategory } from "../format";
import type { BudgetProgress } from "../types";

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function Budgets() {
  const [progress, setProgress] = useState<BudgetProgress[]>([]);
  const [form, setForm] = useState({ category: "", monthly_limit: "" });

  const load = async () => {
    const summary = await api.getSummary(currentMonth());
    setProgress(summary.budget_progress);
  };
  useEffect(() => { load(); }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.createBudget(form.category.toUpperCase().trim(), Number(form.monthly_limit));
    setForm({ category: "", monthly_limit: "" });
    load();
  };

  return (
    <div>
      <form onSubmit={add} className="flex gap-2 mb-4 bg-white p-3 rounded-xl border border-slate-200">
        <input required placeholder="Category (e.g. GROCERIES)" value={form.category}
          onChange={(e) => setForm({ ...form, category: e.target.value })} className="border rounded px-2 py-1" />
        <input required type="number" step="0.01" placeholder="Monthly limit" value={form.monthly_limit}
          onChange={(e) => setForm({ ...form, monthly_limit: e.target.value })} className="border rounded px-2 py-1" />
        <button className="px-3 py-1 rounded bg-slate-900 text-white text-sm">Add budget</button>
      </form>

      <div className="grid gap-3">
        {progress.map((b) => (
          <div key={b.category} className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex justify-between mb-1">
              <span className="font-medium">{prettifyCategory(b.category)}</span>
              <span className="text-sm text-slate-500">
                {formatCurrency(b.spent)} / {formatCurrency(b.limit)}
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className={`h-full ${b.pct > 100 ? "bg-red-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(b.pct, 100)}%` }} />
            </div>
          </div>
        ))}
        {progress.length === 0 && <p className="text-slate-500">No budgets yet.</p>}
      </div>
    </div>
  );
}
