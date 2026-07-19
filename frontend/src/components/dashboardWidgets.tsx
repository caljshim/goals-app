import { useEffect, useState, type ReactNode } from "react";
import {
  Bar, BarChart, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import type { Account, BudgetProgress, Goal, GoalTask, Portfolio, Summary, Transaction } from "../types";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import { filterTransactions } from "../search";
import CategoryTransactions from "./CategoryTransactions";
import MerchantRules from "./MerchantRules";
import PlaidLinkButton from "./PlaidLinkButton";
import type { DashboardWidgetId } from "../dashboardConfig";

const COLORS = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#f43f5e"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(m: string): string {
  const [year, mon] = m.split("-");
  return `${MONTH_NAMES[Number(mon) - 1]} '${year.slice(2)}`;
}

function useSummary() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const load = () => api.getSummary(currentMonth()).then(setSummary);
  useEffect(() => {
    load();
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);
  return { summary, reload: load };
}

function Card({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4">{children}</div>;
}

export function LeftToSpendWidget() {
  const { summary } = useSummary();
  if (!summary) return <p className="text-slate-500">Loading...</p>;
  const totalLeft = summary.budget_progress.reduce((sum, b) => sum + b.remaining, 0);
  return (
    <Card>
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-semibold">Left to spend</h3>
        {summary.budget_progress.length > 0 && (
          <span className={`text-lg font-bold ${totalLeft < 0 ? "text-red-500" : "text-emerald-600"}`}>
            {formatCurrency(totalLeft)} left
          </span>
        )}
      </div>
      {summary.budget_progress.length === 0 && <p className="text-slate-500">No budgets set.</p>}
      <div className="grid gap-3">
        {summary.budget_progress.map((b) => (
          <div key={b.category}>
            <div className="mb-1 flex justify-between gap-2 text-sm">
              <span className="truncate">{prettifyCategory(b.category)}</span>
              <span className="shrink-0 text-slate-500">
                <span className={b.remaining < 0 ? "font-medium text-red-500" : "font-medium text-emerald-600"}>
                  {formatCurrency(b.remaining)} left
                </span>
                {" / "}{formatCurrency(b.limit)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${b.pct > 100 ? "bg-red-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(b.pct, 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function MonthlyAveragesWidget() {
  const { summary } = useSummary();
  const [selectedMonths, setSelectedMonths] = useState<Set<string> | null>(null);
  if (!summary) return <p className="text-slate-500">Loading...</p>;

  const completeSet = new Set(summary.complete_months);
  const defaultMonths = (
    summary.complete_months.length
      ? summary.complete_months
      : summary.monthly_trend.map((m) => m.month).filter((m) => m !== currentMonth())
  ).slice(-3);
  const selected = selectedMonths ?? new Set(defaultMonths);
  const toggleMonth = (month: string) => {
    const next = new Set(selected);
    if (next.has(month)) next.delete(month);
    else next.add(month);
    setSelectedMonths(next);
  };
  const chosen = summary.monthly_trend.filter((m) => selected.has(m.month));
  const divisor = chosen.length || 1;
  const avgIncome = chosen.reduce((sum, m) => sum + m.income, 0) / divisor;
  const avgExpense = chosen.reduce((sum, m) => sum + m.expense, 0) / divisor;
  const avgNet = avgIncome - avgExpense;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-sm text-slate-500">
          Averaging {chosen.length} {chosen.length === 1 ? "month" : "months"}:
        </span>
        {summary.monthly_trend.map((m) => {
          const full = completeSet.has(m.month);
          return (
            <button key={m.month} onClick={() => toggleMonth(m.month)}
              title={full ? undefined : "Incomplete month of data - off by default"}
              className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                selected.has(m.month)
                  ? "border-slate-900 bg-slate-900 text-white"
                  : `border-slate-300 bg-white hover:border-slate-400 ${full ? "text-slate-500" : "text-slate-400 italic"}`
              }`}
            >
              {monthLabel(m.month)}
            </button>
          );
        })}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Avg income / mo" value={avgIncome} tone="text-emerald-600" />
        <Metric label="Avg expenses / mo" value={avgExpense} tone="text-red-500" />
        <Metric label="Avg net / mo" value={avgNet} tone={avgNet < 0 ? "text-red-500" : "text-emerald-600"} />
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <Card>
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`text-2xl font-bold ${tone ?? ""}`}>{formatCurrency(value)}</div>
    </Card>
  );
}

export function SpendingByCategoryWidget() {
  const { summary } = useSummary();
  if (!summary) return <p className="text-slate-500">Loading...</p>;
  const cats = summary.spending_by_category;
  const needsOther = cats.length > COLORS.length;
  const shown = needsOther ? cats.slice(0, COLORS.length - 1) : cats;
  const pieData = shown.map((c) => ({ name: prettifyCategory(c.category), value: c.total }));
  if (needsOther) {
    const otherTotal = cats.slice(COLORS.length - 1).reduce((sum, c) => sum + c.total, 0);
    pieData.push({ name: "Other", value: Math.round(otherTotal * 100) / 100 });
  }
  return (
    <Card>
      <h3 className="mb-2 font-semibold">Spending by category</h3>
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={80} label>
            {pieData.map((d, i) => <Cell key={d.name} fill={d.name === "Other" ? "#94a3b8" : COLORS[i]} />)}
          </Pie>
          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </Card>
  );
}

export function IncomeVsExpenseWidget() {
  const { summary } = useSummary();
  if (!summary) return <p className="text-slate-500">Loading...</p>;
  return (
    <Card>
      <h3 className="mb-2 font-semibold">Income vs expense (6 months)</h3>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={summary.monthly_trend}>
          <XAxis dataKey="month" /><YAxis /><Tooltip formatter={(v) => formatCurrency(Number(v))} /><Legend />
          <Bar dataKey="income" fill="#10b981" /><Bar dataKey="expense" fill="#ef4444" />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

export function RecentTransactionsWidget() {
  const [rows, setRows] = useState<Transaction[]>([]);
  const [query, setQuery] = useState("");
  useEffect(() => { api.getTransactions().then(setRows).catch(() => {}); }, []);
  const visible = filterTransactions(rows, query).slice(0, 8);
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Recent transactions</h3>
        <input placeholder="Search..." value={query} onChange={(e) => setQuery(e.target.value)}
          className="w-52 rounded border px-2 py-1 text-sm" />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {visible.map((t) => (
            <tr key={t.id} className="border-t border-slate-100">
              <td className="py-1.5 pr-2 whitespace-nowrap">{formatDateFull(t.date)}</td>
              <td className="py-1.5 pr-2">{t.merchant_name ?? t.name}</td>
              <td className="py-1.5 pr-2 text-slate-500">{prettifyCategory(t.effective_category)}</td>
              <td className={`py-1.5 text-right ${t.amount < 0 ? "text-emerald-600" : ""}`}>{formatCurrency(t.amount)}</td>
            </tr>
          ))}
          {visible.length === 0 && <tr><td className="py-2 text-slate-500">No transactions.</td></tr>}
        </tbody>
      </table>
    </Card>
  );
}

export function ManualTransactionWidget() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [form, setForm] = useState({ account_id: 0, date: "", name: "", amount: "" });
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.getAccounts().then(setAccounts).catch(() => {}); }, []);
  const addManual = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.createTransaction({
      account_id: Number(form.account_id), date: form.date, name: form.name, amount: Number(form.amount),
    });
    setForm({ account_id: 0, date: "", name: "", amount: "" });
    setSaved(true);
  };
  return (
    <Card>
      <h3 className="mb-3 font-semibold">Add manual transaction</h3>
      <form onSubmit={addManual} className="flex flex-wrap gap-2">
        <select required value={form.account_id} onChange={(e) => setForm({ ...form, account_id: Number(e.target.value) })}
          className="rounded border px-2 py-1">
          <option value={0} disabled>Account</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
          className="rounded border px-2 py-1" />
        <input required placeholder="Description" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded border px-2 py-1" />
        <input required type="number" step="0.01" placeholder="Amount" value={form.amount}
          onChange={(e) => setForm({ ...form, amount: e.target.value })} className="w-32 rounded border px-2 py-1" />
        <button className="rounded bg-slate-900 px-3 py-1 text-sm text-white">Add</button>
        {saved && <span className="self-center text-xs text-emerald-600">Saved</span>}
      </form>
    </Card>
  );
}

export function AccountBalancesWidget() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  useEffect(() => { api.getAccounts().then(setAccounts).catch(() => {}); }, []);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {accounts.map((a) => (
        <Card key={a.id}>
          <div className="text-sm text-slate-500">{prettifyCategory(a.subtype ?? a.type)} ..{a.mask}</div>
          <div className="font-semibold">{a.name}</div>
          <div className="mt-1 text-2xl font-bold">{a.current_balance != null ? formatCurrency(a.current_balance) : "-"}</div>
        </Card>
      ))}
      {accounts.length === 0 && <p className="text-slate-500">No accounts yet.</p>}
    </div>
  );
}

export function AccountSyncWidget() {
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const doSync = async () => {
    setSyncing(true);
    try {
      await api.sync();
      setError(null);
    } catch {
      setError("Failed to sync transactions.");
    } finally {
      setSyncing(false);
    }
  };
  return (
    <Card>
      <div className="flex flex-wrap gap-2">
        <PlaidLinkButton onLinked={() => setError(null)} onError={setError} />
        <button onClick={doSync} disabled={syncing}
          className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium disabled:opacity-50">
          {syncing ? "Syncing..." : "Sync transactions"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </Card>
  );
}

export function BudgetProgressWidget() {
  const { summary } = useSummary();
  if (!summary) return <p className="text-slate-500">Loading...</p>;
  return <BudgetProgressList progress={summary.budget_progress} />;
}

function BudgetProgressList({ progress }: { progress: BudgetProgress[] }) {
  return (
    <div className="grid gap-3">
      {progress.map((b) => (
        <Card key={b.category}>
          <div className="mb-1 flex justify-between">
            <span className="font-medium">{prettifyCategory(b.category)}</span>
            <span className="text-sm text-slate-500">{formatCurrency(b.spent)} / {formatCurrency(b.limit)}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full ${b.pct > 100 ? "bg-red-500" : "bg-emerald-500"}`}
              style={{ width: `${Math.min(b.pct, 100)}%` }} />
          </div>
        </Card>
      ))}
      {progress.length === 0 && <p className="text-slate-500">No budgets yet.</p>}
    </div>
  );
}

export function BudgetFormWidget() {
  const [form, setForm] = useState({ category: "", monthly_limit: "" });
  const [saved, setSaved] = useState(false);
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.createBudget(form.category.toUpperCase().trim(), Number(form.monthly_limit));
    setForm({ category: "", monthly_limit: "" });
    setSaved(true);
  };
  return (
    <Card>
      <h3 className="mb-3 font-semibold">Add budget</h3>
      <form onSubmit={add} className="flex flex-wrap gap-2">
        <input required placeholder="Category" value={form.category}
          onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded border px-2 py-1" />
        <input required type="number" step="0.01" placeholder="Monthly limit" value={form.monthly_limit}
          onChange={(e) => setForm({ ...form, monthly_limit: e.target.value })} className="rounded border px-2 py-1" />
        <button className="rounded bg-slate-900 px-3 py-1 text-sm text-white">Add budget</button>
        {saved && <span className="self-center text-xs text-emerald-600">Saved</span>}
      </form>
    </Card>
  );
}

function goalSection(g: Goal): "daily" | "weekly" | "monthly" | "interval" | "once" | "ongoing" {
  return g.kind === "streak" ? "ongoing" : g.period;
}

function GoalMiniCard({ goal }: { goal: Goal }) {
  const label = goal.unit === "$"
    ? `${formatCurrency(goal.current_value)}${goal.target != null ? ` / ${formatCurrency(goal.target)}` : ""}`
    : `${goal.current_value.toLocaleString()}${goal.target != null ? ` / ${goal.target.toLocaleString()}` : ""}`;
  return (
    <Card>
      <div className="mb-1 flex justify-between gap-2">
        <span className="truncate font-medium">{goal.name}</span>
        <span className={`text-xs ${goal.status === "over" ? "text-red-500" : "text-slate-500"}`}>
          {goal.pct != null ? `${goal.pct}%` : ""}
        </span>
      </div>
      <div className="mb-1 text-sm text-slate-500">{label}</div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full ${goal.status === "over" ? "bg-red-500" : "bg-emerald-500"}`}
          style={{ width: `${Math.min(goal.pct ?? 0, 100)}%` }} />
      </div>
      <div className="mt-1.5 flex flex-wrap gap-2 text-xs text-slate-400">
        {goal.group && <span>{goal.group}</span>}
        {goal.period !== "once" && <span>{goal.period}</span>}
        {goal.period === "weekly" && (goal.weekly_days?.length || goal.weekly_day) && (
          <span>{(goal.weekly_days ?? (goal.weekly_day ? [goal.weekly_day] : [])).join(", ")}</span>
        )}
      </div>
    </Card>
  );
}

export function GoalWidget({ id }: { id: DashboardWidgetId }) {
  const [goals, setGoals] = useState<Goal[]>([]);
  useEffect(() => { api.getGoals().then(setGoals).catch(() => {}); }, []);
  let visible: Goal[] = [];
  if (id.startsWith("goal:")) {
    const goalId = Number(id.slice("goal:".length));
    visible = goals.filter((g) => g.id === goalId);
  } else if (id.startsWith("goal-name:")) {
    const name = id.slice("goal-name:".length).toLowerCase();
    visible = goals.filter((g) => g.name.toLowerCase() === name);
  } else if (id.startsWith("goal-group:")) {
    const group = id.slice("goal-group:".length);
    visible = goals.filter((g) => g.group === group);
  } else if (id.startsWith("goal-section:")) {
    const section = id.slice("goal-section:".length);
    visible = goals.filter((g) => goalSection(g) === section);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {visible.map((g) => <GoalMiniCard key={g.id} goal={g} />)}
      {goals.length === 0 && <p className="text-slate-500">No goals yet.</p>}
      {goals.length > 0 && visible.length === 0 && <p className="text-slate-500">No matching goals.</p>}
    </div>
  );
}

export function GoalTodoWidget({ scope, allowOverdue = false, onChange }: {
  scope: "day" | "week" | "month";
  allowOverdue?: boolean;
  onChange?: () => void;
}) {
  const [tasks, setTasks] = useState<GoalTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.getGoalTasks(scope).then(setTasks).catch(() => setError("Could not load goal tasks."));
  useEffect(() => { load(); }, [scope]);

  const toggle = async (task: GoalTask) => {
    if (task.missed && !allowOverdue) return;
    await api.setGoalCheckin(task.goal_id, task.scheduled_for, !task.completed, allowOverdue);
    load();
    onChange?.();
  };

  return (
    <div className="divide-y divide-slate-100 border-y border-slate-200 bg-white">
      {tasks.map((task) => (
        <label key={`${task.goal_id}-${task.scheduled_for}`}
          className={`flex items-center gap-3 px-1 py-3 ${task.missed ? "bg-red-50 text-red-700" : ""}`}>
          <input type="checkbox" checked={task.completed} disabled={task.missed && !allowOverdue}
            onChange={() => toggle(task)} className="h-4 w-4 accent-slate-900" />
          <span className={`min-w-0 flex-1 ${task.completed ? "text-slate-400 line-through" : ""}`}>{task.name}</span>
          <span className="shrink-0 text-xs">
            {task.missed ? `Late · ${formatDateFull(task.scheduled_for)}` : formatDateFull(task.scheduled_for)}
          </span>
        </label>
      ))}
      {!error && tasks.length === 0 && <p className="py-4 text-sm text-slate-500">Nothing scheduled.</p>}
      {error && <p className="py-4 text-sm text-red-600">{error}</p>}
    </div>
  );
}

function usePortfolio() {
  const [data, setData] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getPortfolio().then(setData).catch(() => setError("Portfolio unavailable."));
  }, []);
  return { data, error };
}

const usd = (n: number | null) => n === null ? "-" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function PortfolioSummaryWidget() {
  const { data, error } = usePortfolio();
  if (error) return <Card><p className="text-sm text-amber-700">{error}</p></Card>;
  if (!data) return <p className="text-slate-500">Loading portfolio...</p>;
  return (
    <div className="grid gap-3">
      {data.accounts.map((a) => (
        <Card key={a.account_number}>
          <div className="flex justify-between gap-3">
            <div>
              <div className="font-semibold">{a.nickname || a.account_number}</div>
              <div className="text-xs text-slate-500">{a.type}</div>
            </div>
            <div className="text-right text-xl font-bold">{usd(a.net_liquidating_value)}</div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div><div className="text-xs text-slate-500">Cash</div>{usd(a.cash_balance)}</div>
            <div><div className="text-xs text-slate-500">Stock BP</div>{usd(a.equity_buying_power)}</div>
            <div><div className="text-xs text-slate-500">Options BP</div>{usd(a.derivative_buying_power)}</div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function PortfolioPositionsWidget() {
  const { data, error } = usePortfolio();
  if (error) return <Card><p className="text-sm text-amber-700">{error}</p></Card>;
  if (!data) return <p className="text-slate-500">Loading positions...</p>;
  const positions = data.accounts.flatMap((a) => a.positions.map((p) => ({ ...p, account: a.nickname || a.account_number })));
  return (
    <Card>
      <h3 className="mb-2 font-semibold">Open positions</h3>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr><th className="py-1">Symbol</th><th className="py-1">Type</th><th className="py-1 text-right">Qty</th><th className="py-1 text-right">Value</th></tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={`${p.account}-${p.symbol}`} className="border-t border-slate-100">
              <td className="py-1.5 font-medium">{p.symbol}</td>
              <td className="py-1.5 text-slate-500">{p.instrument_type}</td>
              <td className="py-1.5 text-right">{p.quantity}</td>
              <td className="py-1.5 text-right">{usd(p.market_value)}</td>
            </tr>
          ))}
          {positions.length === 0 && <tr><td className="py-2 text-slate-500">No open positions.</td></tr>}
        </tbody>
      </table>
    </Card>
  );
}

export function DashboardWidgetContent({ id, onChange }: { id: DashboardWidgetId; onChange?: () => void }) {
  if (id === "left-to-spend") return <LeftToSpendWidget />;
  if (id === "monthly-averages") return <MonthlyAveragesWidget />;
  if (id === "spending-by-category") return <SpendingByCategoryWidget />;
  if (id === "income-vs-expense") return <IncomeVsExpenseWidget />;
  if (id === "category-transactions") return <CategoryTransactions onChange={onChange} />;
  if (id === "recent-transactions") return <RecentTransactionsWidget />;
  if (id === "merchant-rules") return <MerchantRules signal={0} onChange={onChange} />;
  if (id === "manual-transaction") return <ManualTransactionWidget />;
  if (id === "account-balances") return <AccountBalancesWidget />;
  if (id === "account-sync") return <AccountSyncWidget />;
  if (id === "budget-progress") return <BudgetProgressWidget />;
  if (id === "budget-form") return <BudgetFormWidget />;
  if (id === "goal-todo-day") return <GoalTodoWidget scope="day" />;
  if (id === "goal-todo-week") return <GoalTodoWidget scope="week" />;
  if (id === "goal-todo-month") return <GoalTodoWidget scope="month" />;
  if (id.startsWith("goal:") || id.startsWith("goal-name:") || id.startsWith("goal-group:") || id.startsWith("goal-section:")) {
    return <GoalWidget id={id} />;
  }
  if (id === "portfolio-summary") return <PortfolioSummaryWidget />;
  return <PortfolioPositionsWidget />;
}
