import { useEffect, useState } from "react";
import { api } from "../api";
import { AddBudgetForm, BudgetPeriodPicker, BudgetProgressList } from "../components/BudgetWidgets";
import { formatCurrency } from "../format";
import type { BudgetPeriod, BudgetProgress } from "../types";

const PERIOD_KEY = "money.ui.budgets.period";
function currentMonth(): string {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export default function Budgets() {
  const [progress, setProgress] = useState<BudgetProgress[]>([]);
  const [period, setPeriod] = useState<BudgetPeriod>(() =>
    (localStorage.getItem(PERIOD_KEY) as BudgetPeriod | null) ?? "monthly");
  const load = () => api.getSummary(currentMonth()).then((summary) => setProgress(summary.budget_progress));
  useEffect(() => { load(); }, []);
  const choosePeriod = (value: BudgetPeriod) => { setPeriod(value); localStorage.setItem(PERIOD_KEY, value); };
  const rows = progress.filter((budget) => budget.period === period);
  const remaining = rows.reduce((total, budget) => total + budget.remaining, 0);
  const remove = async (id: number) => { await api.deleteBudget(id); load(); };

  return (
    <div className="grid gap-4">
      <BudgetPeriodPicker value={period} onChange={choosePeriod} />
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-sm text-slate-500">
          {period === "daily" ? "Left today" : period === "weekly" ? "Left this week" : "Left this month"}
        </div>
        <div className={`text-3xl font-bold ${remaining < 0 ? "text-red-500" : "text-emerald-600"}`}>
          {formatCurrency(remaining)}
        </div>
      </div>
      <BudgetProgressList progress={progress} period={period} onDelete={remove} />
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 font-semibold">Add budget</h3>
        <AddBudgetForm defaultPeriod={period} onSaved={load} />
      </div>
    </div>
  );
}
