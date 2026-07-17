import { useEffect, useState } from "react";
import {
  Bar, BarChart, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import CategoryTransactions from "../components/CategoryTransactions";
import { formatCurrency, prettifyCategory } from "../format";
import type { Summary, Transaction } from "../types";

const COLORS = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#f43f5e"];

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2026-07" -> "Jul '26"
function monthLabel(m: string): string {
  const [year, mon] = m.split("-");
  return `${MONTH_NAMES[Number(mon) - 1]} '${year.slice(2)}`;
}

// "2026-07-12" -> "Jul 12" (string parse — avoids Date() UTC off-by-one)
function shortDate(iso: string): string {
  const [, mon, day] = iso.split("-");
  return `${MONTH_NAMES[Number(mon) - 1]} ${Number(day)}`;
}

function Tile({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`text-2xl font-bold ${tone ?? ""}`}>{formatCurrency(value)}</div>
    </div>
  );
}

export default function Dashboard() {
  const [s, setS] = useState<Summary | null>(null);
  const [selectedMonths, setSelectedMonths] = useState<Set<string> | null>(null);
  const [monthTxns, setMonthTxns] = useState<Transaction[]>([]);
  const [openBudgets, setOpenBudgets] = useState<Set<string>>(new Set());
  const loadSummary = () => {
    api.getSummary(currentMonth()).then(setS);
    // current month's transactions feed the budget drilldowns
    api.getTransactions({ start: `${currentMonth()}-01` }).then(setMonthTxns);
  };
  useEffect(() => {
    loadSummary();
    // Tabbing back to the app refetches instantly — local read, costs nothing.
    window.addEventListener("focus", loadSummary);
    return () => window.removeEventListener("focus", loadSummary);
  }, []);
  if (!s) return <p className="text-slate-500">Loading…</p>;

  // Averages for the top tiles: default to the last 3 months the data fully covers
  // (excludes the partial current month AND a partial leading month, e.g. a mid-month
  // Plaid pull) until the user toggles the month chips themselves.
  const completeSet = new Set(s.complete_months);
  const defaultMonths = (
    s.complete_months.length
      ? s.complete_months
      : s.monthly_trend.map((m) => m.month).filter((m) => m !== currentMonth())
  ).slice(-3);
  const selected = selectedMonths ?? new Set(defaultMonths);
  const toggleMonth = (month: string) => {
    const next = new Set(selected);
    if (next.has(month)) next.delete(month);
    else next.add(month);
    setSelectedMonths(next);
  };
  const chosen = s.monthly_trend.filter((m) => selected.has(m.month));
  const divisor = chosen.length || 1;
  const avgIncome = chosen.reduce((sum, m) => sum + m.income, 0) / divisor;
  const avgExpense = chosen.reduce((sum, m) => sum + m.expense, 0) / divisor;
  const avgNet = avgIncome - avgExpense;
  const totalLeft = s.budget_progress.reduce((sum, b) => sum + b.remaining, 0);

  const toggleBudget = (category: string) =>
    setOpenBudgets((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });

  // This month's spending in a budget category, grouped by merchant (largest first).
  // Mirrors the backend's "spent": expenses only (amount >= 0).
  const merchantsFor = (category: string) => {
    const byMerchant = new Map<string, { total: number; count: number; last: string }>();
    for (const t of monthTxns) {
      if (t.effective_category !== category || t.amount < 0) continue;
      const k = t.merchant_name ?? t.name;
      const g = byMerchant.get(k) ?? { total: 0, count: 0, last: "" };
      g.total += t.amount;
      g.count += 1;
      if (t.date > g.last) g.last = t.date; // ISO strings compare chronologically
      byMerchant.set(k, g);
    }
    return [...byMerchant.entries()]
      .map(([name, g]) => ({ name, ...g }))
      .sort((a, b) => b.total - a.total);
  };

  // Keep colors 1:1 with categories: show up to COLORS.length slices, folding any
  // overflow into a single neutral "Other" bucket so no hue is ever reused.
  const cats = s.spending_by_category;
  const needsOther = cats.length > COLORS.length;
  const shown = needsOther ? cats.slice(0, COLORS.length - 1) : cats;
  const pieData = shown.map((c) => ({ name: prettifyCategory(c.category), value: c.total }));
  if (needsOther) {
    const otherTotal = cats.slice(COLORS.length - 1).reduce((sum, c) => sum + c.total, 0);
    pieData.push({ name: "Other", value: Math.round(otherTotal * 100) / 100 });
  }

  return (
    <div className="grid gap-4">
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="font-semibold">Left to spend</h3>
          {s.budget_progress.length > 0 && (
            <span className={`text-lg font-bold ${totalLeft < 0 ? "text-red-500" : "text-emerald-600"}`}>
              {formatCurrency(totalLeft)} left
            </span>
          )}
        </div>
        {s.budget_progress.length === 0 && (
          <p className="text-slate-500">No budgets set — ask the assistant to “suggest a budget”.</p>
        )}
        {s.budget_progress.map((b) => {
          const open = openBudgets.has(b.category);
          const merchants = open ? merchantsFor(b.category) : [];
          return (
            <div key={b.category} className="mb-3">
              <button
                onClick={() => toggleBudget(b.category)}
                title="See this month's spending in this budget"
                className="w-full flex items-center justify-between gap-2 text-sm mb-1 text-left"
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="text-slate-400 w-3 shrink-0">{open ? "▾" : "▸"}</span>
                  <span className="truncate">{prettifyCategory(b.category)}</span>
                </span>
                <span className="text-slate-500 shrink-0">
                  <span className={`font-medium ${b.remaining < 0 ? "text-red-500" : "text-emerald-600"}`}>
                    {formatCurrency(b.remaining)} left
                  </span>
                  {" · "}{formatCurrency(b.spent)} / {formatCurrency(b.limit)}
                </span>
              </button>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div className={`h-full ${b.pct > 100 ? "bg-red-500" : "bg-emerald-500"}`}
                  style={{ width: `${Math.min(b.pct, 100)}%` }} />
              </div>
              {open && (
                <div className="mt-1.5 ml-1 border-l-2 border-slate-100 pl-3">
                  {merchants.length === 0 && (
                    <p className="text-xs text-slate-400 py-0.5">No spending here yet this month.</p>
                  )}
                  {merchants.map((m) => (
                    <div key={m.name} className="flex justify-between gap-2 text-xs text-slate-600 py-0.5">
                      <span className="truncate">
                        {m.name}
                        {m.count > 1 && <span className="ml-1 text-slate-400">×{m.count}</span>}
                      </span>
                      <span className="shrink-0">
                        <span className="text-slate-400">last {shortDate(m.last)}</span>
                        {" · "}{formatCurrency(m.total)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div>
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-sm text-slate-500 mr-1">
            Averaging {chosen.length} {chosen.length === 1 ? "month" : "months"}:
          </span>
          {s.monthly_trend.map((m) => {
            const full = completeSet.has(m.month);
            return (
              <button
                key={m.month}
                onClick={() => toggleMonth(m.month)}
                title={full ? undefined : "Incomplete month of data — off by default"}
                className={`px-2 py-0.5 rounded-full text-xs border transition-colors ${
                  selected.has(m.month)
                    ? "bg-slate-900 text-white border-slate-900"
                    : `bg-white border-slate-300 hover:border-slate-400 ${full ? "text-slate-500" : "text-slate-400 italic"}`
                }`}
              >
                {monthLabel(m.month)}
              </button>
            );
          })}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Tile label="Avg income / mo" value={avgIncome} tone="text-emerald-600" />
          <Tile label="Avg expenses / mo" value={avgExpense} tone="text-red-500" />
          <Tile label="Avg net / mo" value={avgNet} tone={avgNet < 0 ? "text-red-500" : "text-emerald-600"} />
        </div>
        <p className="mt-1.5 text-xs text-slate-400">
          Expenses are net of Zelle/Venmo with people (reimbursements in, payments out). Card payments and account transfers excluded.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="font-semibold mb-2">Spending by category</h3>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={80} label>
                {pieData.map((d, i) => <Cell key={i} fill={d.name === "Other" ? "#94a3b8" : COLORS[i]} />)}
              </Pie>
              <Tooltip formatter={(v) => formatCurrency(Number(v))} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="font-semibold mb-2">Income vs expense (6 months)</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={s.monthly_trend}>
              <XAxis dataKey="month" /><YAxis /><Tooltip formatter={(v) => formatCurrency(Number(v))} /><Legend />
              <Bar dataKey="income" fill="#10b981" /><Bar dataKey="expense" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <CategoryTransactions onChange={loadSummary} />
    </div>
  );
}
