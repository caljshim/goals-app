import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import type { BudgetPeriod, BudgetProgress } from "../types";

export const BUDGET_PERIODS: BudgetPeriod[] = ["daily", "weekly", "monthly"];
const EXPANDED_KEY = "money.ui.budgets.expanded";

export function BudgetPeriodPicker({ value, onChange }: {
  value: BudgetPeriod; onChange: (period: BudgetPeriod) => void;
}) {
  return (
    <div className="grid grid-cols-3 rounded-lg bg-slate-100 p-1" aria-label="Budget period">
      {BUDGET_PERIODS.map((period) => (
        <button key={period} type="button" onClick={() => onChange(period)}
          className={`rounded-md px-3 py-1.5 text-sm capitalize ${value === period ? "bg-white font-semibold text-slate-900 shadow-sm" : "text-slate-500"}`}>
          {period === "daily" ? "Today" : period === "weekly" ? "This week" : "This month"}
        </button>
      ))}
    </div>
  );
}

function loadExpanded(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) ?? "[]") as string[]); }
  catch { return new Set(); }
}

export function BudgetProgressList({ progress, period, onDelete }: {
  progress: BudgetProgress[]; period: BudgetPeriod; onDelete?: (budgetId: number) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(loadExpanded);
  const rows = progress.filter((budget) => budget.period === period);
  const toggle = (key: string) => {
    const next = new Set(expanded);
    if (next.has(key)) next.delete(key); else next.add(key);
    setExpanded(next);
    localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
  };
  return (
    <div className="grid gap-3">
      {rows.map((budget) => {
        const key = `${budget.category}:${budget.period}`;
        const open = expanded.has(key);
        return (
          <div key={key} className="rounded-xl border border-slate-200 bg-white p-4">
            <button type="button" onClick={() => toggle(key)} className="flex w-full items-center gap-2 text-left">
              <span className="text-slate-400">{open ? "▾" : "▸"}</span>
              <span className="min-w-0 flex-1 truncate font-medium">{prettifyCategory(budget.category)}</span>
              <span className={`shrink-0 text-sm font-semibold ${budget.remaining < 0 ? "text-red-500" : "text-emerald-600"}`}>
                {formatCurrency(budget.remaining)} left
              </span>
            </button>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${budget.pct > 100 ? "bg-red-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(budget.pct, 100)}%` }} />
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {formatCurrency(budget.spent)} / {formatCurrency(budget.limit)}
            </div>
            {open && (
              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
                <span>{formatDateFull(budget.window_start)} – {formatDateFull(budget.window_end)}</span>
                {onDelete && <button type="button" onClick={() => onDelete(budget.budget_id)} className="text-red-500">Remove</button>}
              </div>
            )}
          </div>
        );
      })}
      {rows.length === 0 && <p className="text-sm text-slate-500">No {period} budgets yet.</p>}
    </div>
  );
}

export function AddBudgetForm({ defaultPeriod, onSaved }: {
  defaultPeriod: BudgetPeriod; onSaved?: () => void;
}) {
  const [category, setCategory] = useState("");
  const [limit, setLimit] = useState("");
  const [period, setPeriod] = useState<BudgetPeriod>(defaultPeriod);
  const [saving, setSaving] = useState(false);
  useEffect(() => setPeriod(defaultPeriod), [defaultPeriod]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true);
    try {
      await api.createBudget(category.toUpperCase().trim(), Number(limit), period);
      setCategory(""); setLimit(""); onSaved?.();
    } finally { setSaving(false); }
  };
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-xs text-slate-500">Category
        <input required placeholder="e.g. GROCERIES" value={category} onChange={(e) => setCategory(e.target.value)}
          className="rounded border px-2 py-1 text-sm" />
      </label>
      <label className="flex flex-col text-xs text-slate-500">Limit
        <input required type="number" min="0.01" step="0.01" placeholder="Amount" value={limit} onChange={(e) => setLimit(e.target.value)}
          className="w-28 rounded border px-2 py-1 text-sm" />
      </label>
      <label className="flex flex-col text-xs text-slate-500">Resets
        <select value={period} onChange={(e) => setPeriod(e.target.value as BudgetPeriod)} className="rounded border px-2 py-1 text-sm">
          {BUDGET_PERIODS.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}
        </select>
      </label>
      <button disabled={saving} className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50">Add budget</button>
    </form>
  );
}
