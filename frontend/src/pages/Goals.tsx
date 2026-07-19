import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCurrency, formatDateFull, formatTimestampDate, prettifyCategory } from "../format";
import { goalPace, groupAggregate } from "../goals";
import GoalChart from "../components/GoalChart";
import CategoryChart from "../components/CategoryChart";
import { GoalTodoWidget } from "../components/dashboardWidgets";
import type { Account, Goal, GoalKind, GoalPeriod, GoalDirection, GoalTask } from "../types";

const KINDS: { value: GoalKind; label: string; icon: string }[] = [
  { value: "save", label: "Savings goal", icon: "🎯" },
  { value: "spend_cap", label: "Spending cap", icon: "🧾" },
  { value: "numeric", label: "Numeric goal", icon: "📈" },
  { value: "streak", label: "Streak / days-since", icon: "🔥" },
];
const ICON: Record<GoalKind, string> = { save: "🎯", spend_cap: "🧾", numeric: "📈", streak: "🔥" };
const PERIOD_LABEL: Record<GoalPeriod, string> = { once: "", daily: "today", weekly: "this week", monthly: "this month", interval: "on its interval" };
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] as const;

// Dashboard sections, in order. Streaks are continuous -> "Ongoing".
const SECTIONS: { key: string; label: string }[] = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "interval", label: "Every N days" },
  { key: "once", label: "One-time" },
  { key: "ongoing", label: "Ongoing" },
];
const sectionOf = (g: Goal): string => (g.kind === "streak" ? "ongoing" : g.period);

function formatValue(v: number, unit: string): string {
  if (unit === "$") return formatCurrency(v);
  if (unit === "days") return `${v} ${v === 1 ? "day" : "days"}`;
  return v.toLocaleString();
}

function formatLocalTime(value: string): string {
  const [hour, minute] = value.split(":").map(Number);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return value;
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" })
    .format(new Date(2000, 0, 1, hour, minute));
}

function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}

const emptyForm = {
  kind: "save" as GoalKind, period: "once" as GoalPeriod, direction: "reach" as GoalDirection,
  name: "", target: "", account_id: "", category: "", current: "", since: "", deadline: "", step: "1", group: "", weekly_days: [] as string[],
  reset_time: "00:00", weekly_reset_day: "sunday", monthly_reset_day: "1", interval_days: "2",
};

export default function Goals() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<GoalTask[]>([]);
  const [taskScope, setTaskScope] = useState<"day" | "week" | "month">("day");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [form, setForm] = useState({ ...emptyForm });
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [expandedGoals, setExpandedGoals] = useState<Set<number>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [editGoalId, setEditGoalId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState({ name: "", target: "", group: "", deadline: "", category: "", weekly_days: [] as string[],
    reset_time: "00:00", weekly_reset_day: "sunday", monthly_reset_day: "1", interval_days: "2" });
  const [raiseId, setRaiseId] = useState<number | null>(null);
  const [raiseValue, setRaiseValue] = useState("");

  const load = () => api.getGoals().then(setGoals).catch(() => setError("Failed to load goals."));
  const loadTasks = () => Promise.all([api.getGoalTasks("day"), api.getGoalTasks("week"), api.getGoalTasks("month")])
    .then((groups) => setTasks(groups.flat()));
  useEffect(() => { load(); loadTasks(); api.getAccounts().then(setAccounts); }, []);

  const set = (k: keyof typeof emptyForm, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const k = form.kind;
    const body: Record<string, unknown> = { name: form.name.trim(), kind: k };
    if (k !== "streak") body.target = Number(form.target);
    if (k === "save") {
      if (form.account_id) body.account_id = Number(form.account_id);
      else if (form.current) body.current = Number(form.current);
    }
    if (k === "spend_cap") body.category = form.category.trim().toUpperCase().replace(/\s+/g, "_");
    if (k === "numeric") {
      if (form.current) body.current = Number(form.current);
      body.direction = form.direction;
    }
    if (k === "streak") {
      if (form.since) body.since = form.since;
      if (form.target) body.target = Number(form.target);
    } else {
      body.period = form.period;
      if (form.period === "weekly") body.weekly_days = form.weekly_days;
      if (["daily", "weekly", "interval"].includes(form.period)) body.reset_time = form.reset_time;
      if (form.period === "weekly") body.weekly_reset_day = form.weekly_reset_day;
      if (form.period === "monthly") body.monthly_reset_day = Number(form.monthly_reset_day);
      if (form.period === "interval") body.interval_days = Number(form.interval_days);
    }
    if (form.deadline && (k === "save" || k === "numeric")) body.deadline = form.deadline;
    if (k === "save" || k === "numeric") body.step = Number(form.step) || 1;
    if (form.group.trim()) body.group = form.group.trim();
    try {
      await api.createGoal(body);
      setForm({ ...emptyForm, kind: k });
      setError(null);
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to create goal.");
    }
  };

  // Tally a manual goal: −/+ nudge by the goal's step; click the number to set a total.
  const bump = async (g: Goal, sign: number) => {
    if (sign < 0) await api.setGoalProgress(g.id, { current: Math.max(0, g.current_value - g.step) });
    else await api.setGoalProgress(g.id, { add: g.step });
    load();
  };
  const startEdit = (g: Goal) => { setEditingId(g.id); setEditValue(String(g.current_value)); };
  const commitEdit = async (g: Goal) => {
    const v = Number(editValue);
    setEditingId(null);
    if (!Number.isNaN(v)) { await api.setGoalProgress(g.id, { current: v }); load(); }
  };
  const reset = async (g: Goal) => { await api.resetGoal(g.id); load(); };
  const remove = async (g: Goal) => { await api.deleteGoal(g.id); load(); };

  // Expand/collapse a goal's chart individually, or a whole category at once.
  const toggleGoal = (id: number) =>
    setExpandedGoals((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  const toggleCategory = (name: string) =>
    setExpandedGroups((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });

  const startGoalEdit = (g: Goal) => {
    setEditGoalId(g.id);
    setEditDraft({
      name: g.name, target: g.target != null ? String(g.target) : "",
      group: g.group ?? "", deadline: g.deadline ?? "", category: g.category ?? "",
      weekly_days: g.weekly_days ?? (g.weekly_day ? [g.weekly_day] : []),
      reset_time: g.reset_time ?? "00:00", weekly_reset_day: g.weekly_reset_day ?? "sunday",
      monthly_reset_day: String(g.monthly_reset_day ?? 1), interval_days: String(g.interval_days ?? 2),
    });
  };
  const saveGoalEdit = async (g: Goal) => {
    const body: Record<string, unknown> = { name: editDraft.name.trim(), group: editDraft.group.trim() || null };
    if (editDraft.target !== "") body.target = Number(editDraft.target);
    if (g.kind === "save" || g.kind === "numeric") body.deadline = editDraft.deadline || null;
    if (g.kind === "spend_cap") body.category = editDraft.category.trim().toUpperCase().replace(/\s+/g, "_");
    if (g.period === "weekly") body.weekly_days = editDraft.weekly_days;
    if (["daily", "weekly", "interval"].includes(g.period)) body.reset_time = editDraft.reset_time;
    if (g.period === "weekly") body.weekly_reset_day = editDraft.weekly_reset_day;
    if (g.period === "monthly") body.monthly_reset_day = Number(editDraft.monthly_reset_day);
    if (g.period === "interval") body.interval_days = Number(editDraft.interval_days);
    await api.updateGoal(g.id, body);
    setEditGoalId(null); load();
  };

  // Raise a reached goal: logs the cleared target as a milestone, sets a new higher one.
  const doRaise = async (g: Goal) => {
    const v = Number(raiseValue);
    if (!v) return;
    await api.raiseGoal(g.id, v);
    setRaiseId(null); setRaiseValue(""); load();
  };

  const isManual = (g: Goal) => (g.kind === "save" && g.account_id === null) || g.kind === "numeric";

  const card = (g: Goal) => {
    const manual = isManual(g);
    const scheduledDays = g.weekly_days ?? (g.weekly_day ? [g.weekly_day] : []);
    const hasMissedTask = tasks.some((task) => task.goal_id === g.id && task.missed);
    const expanded = expandedGoals.has(g.id);
    const pace = manual ? goalPace(g.history, g.target) : null;
    const editing = editGoalId === g.id;
    return (
      <div key={g.id} className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="font-medium min-w-0 truncate">{ICON[g.kind]} {g.name}</span>
          <span className="flex items-center gap-2 shrink-0 text-slate-300">
            <button onClick={() => (editing ? setEditGoalId(null) : startGoalEdit(g))} title="Edit goal"
              className="hover:text-slate-600">✎</button>
            <button onClick={() => remove(g)} title="Delete goal" className="hover:text-red-500">✕</button>
          </span>
        </div>

        {editing ? (
          <div className="space-y-1.5 text-xs">
            <input value={editDraft.name} onChange={(e) => setEditDraft({ ...editDraft, name: e.target.value })}
              placeholder="Name" className="border rounded px-2 py-1 w-full" />
            {g.kind !== "streak" && (
              <input type="number" step="0.01" value={editDraft.target}
                onChange={(e) => setEditDraft({ ...editDraft, target: e.target.value })}
                placeholder="Target" className="border rounded px-2 py-1 w-full" />
            )}
            {g.kind === "spend_cap" && (
              <input value={editDraft.category} onChange={(e) => setEditDraft({ ...editDraft, category: e.target.value })}
                placeholder="Category (e.g. EATING_OUT)" className="border rounded px-2 py-1 w-full" />
            )}
            <input value={editDraft.group} onChange={(e) => setEditDraft({ ...editDraft, group: e.target.value })}
              placeholder="Group (optional)" className="border rounded px-2 py-1 w-full" />
            {g.period === "weekly" && (
              <div className="flex flex-wrap gap-1" aria-label="Scheduled days">
                {WEEKDAYS.map((day) => {
                  const selected = editDraft.weekly_days.includes(day);
                  return <button key={day} type="button" onClick={() => setEditDraft({
                    ...editDraft,
                    weekly_days: selected ? editDraft.weekly_days.filter((d) => d !== day) : [...editDraft.weekly_days, day],
                  })} className={`rounded border px-2 py-1 ${selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-600"}`}>
                    {day.slice(0, 3).toUpperCase()}
                  </button>;
                })}
              </div>
            )}
            {(["daily", "weekly", "interval"] as GoalPeriod[]).includes(g.period) && (
              <label className="flex items-center justify-between gap-2 text-slate-500">Reset time
                <input type="time" value={editDraft.reset_time}
                  onChange={(e) => setEditDraft({ ...editDraft, reset_time: e.target.value })}
                  className="rounded border px-2 py-1" />
              </label>
            )}
            {g.period === "weekly" && (
              <label className="flex items-center justify-between gap-2 text-slate-500">Week resets
                <select value={editDraft.weekly_reset_day}
                  onChange={(e) => setEditDraft({ ...editDraft, weekly_reset_day: e.target.value })}
                  className="rounded border px-2 py-1">
                  {WEEKDAYS.map((day) => <option key={day} value={day}>{day[0].toUpperCase() + day.slice(1)}</option>)}
                </select>
              </label>
            )}
            {g.period === "monthly" && (
              <label className="flex items-center justify-between gap-2 text-slate-500">Reset day
                <input type="number" min="1" max="28" value={editDraft.monthly_reset_day}
                  onChange={(e) => setEditDraft({ ...editDraft, monthly_reset_day: e.target.value })}
                  className="w-20 rounded border px-2 py-1" />
              </label>
            )}
            {g.period === "interval" && (
              <label className="flex items-center justify-between gap-2 text-slate-500">Every N days
                <input type="number" min="2" value={editDraft.interval_days}
                  onChange={(e) => setEditDraft({ ...editDraft, interval_days: e.target.value })}
                  className="w-20 rounded border px-2 py-1" />
              </label>
            )}
            {(g.kind === "save" || g.kind === "numeric") && (
              <input type="date" value={editDraft.deadline}
                onChange={(e) => setEditDraft({ ...editDraft, deadline: e.target.value })}
                className="border rounded px-2 py-1 w-full" />
            )}
            <div className="flex gap-2 pt-0.5">
              <button onClick={() => saveGoalEdit(g)} className="px-2 py-1 rounded bg-slate-900 text-white">Save</button>
              <button onClick={() => setEditGoalId(null)} className="px-2 py-1 text-slate-500">Cancel</button>
            </div>
          </div>
        ) : g.kind === "streak" ? (
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold">{g.days}</span>
              <span className="text-slate-500 text-sm">{g.days === 1 ? "day" : "days"}</span>
              <span className="ml-auto text-xs text-slate-400">best: {g.best_days}</span>
            </div>
            {g.target != null && (
              <>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden my-2">
                  <div className={`h-full ${g.status === "milestone" ? "bg-emerald-500" : "bg-sky-500"}`}
                    style={{ width: `${Math.min(g.pct ?? 0, 100)}%` }} />
                </div>
                <div className="text-xs text-slate-500">
                  {g.status === "milestone" ? "🎉 milestone reached" : `milestone: ${g.target} days`}
                </div>
              </>
            )}
            <button onClick={() => reset(g)}
              className="mt-2 text-xs text-slate-500 hover:text-slate-700 border border-slate-200 rounded px-2 py-1">
              ↺ I slipped — reset
            </button>
          </div>
        ) : g.period === "weekly" && scheduledDays.length > 0 ? (
          <div className="divide-y divide-slate-100 border-y border-slate-100">
            {tasks.filter((task) => task.goal_id === g.id).map((task) => (
              <label key={task.scheduled_for}
                className={`flex items-center gap-2 py-2 text-sm ${task.missed ? "text-red-700" : ""}`}>
                <input type="checkbox" checked={task.completed} onChange={async () => {
                  await api.setGoalCheckin(g.id, task.scheduled_for, !task.completed, true);
                  loadTasks();
                }} className="h-4 w-4 accent-slate-900" />
                <span className={task.completed ? "text-slate-400 line-through" : ""}>
                  {new Date(`${task.scheduled_for}T12:00:00`).toLocaleDateString(undefined, { weekday: "long" })}
                </span>
                <span className="ml-auto text-xs text-slate-400">{formatDateFull(task.scheduled_for)}</span>
                {task.missed && <span className="text-xs font-semibold text-red-600">Late</span>}
              </label>
            ))}
            {tasks.filter((task) => task.goal_id === g.id).length === 0 && (
              <p className="py-2 text-sm text-slate-500">No scheduled days in this window.</p>
            )}
            <p className="pt-2 text-xs text-slate-400">
              Resets {capitalize(g.weekly_reset_day ?? "sunday")} at {formatLocalTime(g.reset_time ?? "00:00")} local time
            </p>
          </div>
        ) : (
          <div>
            <div className="flex justify-between items-baseline mb-1">
              <span className="text-sm inline-flex items-center gap-1">
                {manual ? (
                  <span className="inline-flex items-center gap-1">
                    <button onClick={() => bump(g, -1)} disabled={g.current_value <= 0}
                      className="w-5 h-5 leading-none rounded border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40">−</button>
                    {editingId === g.id ? (
                      <input autoFocus type="number" step="0.01" value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={() => commitEdit(g)}
                        onKeyDown={(e) => { if (e.key === "Enter") commitEdit(g); if (e.key === "Escape") setEditingId(null); }}
                        className="w-20 border rounded px-1 text-sm" />
                    ) : (
                      <button onClick={() => startEdit(g)} title="Click to set the total"
                        className="font-semibold underline decoration-dotted decoration-slate-300">
                        {formatValue(g.current_value, g.unit)}
                      </button>
                    )}
                    <button onClick={() => bump(g, 1)}
                      className="w-5 h-5 leading-none rounded border border-slate-200 text-slate-500 hover:bg-slate-50">+</button>
                  </span>
                ) : (
                  <span className="font-semibold">{formatValue(g.current_value, g.unit)}</span>
                )}
                {g.target != null && <span className="text-slate-500"> / {formatValue(g.target, g.unit)}</span>}
              </span>
              <span className={`text-xs ${g.status === "over" ? "text-red-500" : "text-slate-500"}`}>
                {g.pct != null ? `${g.pct}%` : ""}
                {g.status === "over" && " · over"}
                {g.status === "reached" && " · reached ✓"}
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className={`h-full ${g.status === "over" ? "bg-red-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(g.pct ?? 0, 100)}%` }} />
            </div>
            <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-400">
              {g.linked_label && <span>🔗 {g.kind === "spend_cap" ? prettifyCategory(g.linked_label) : g.linked_label}</span>}
              {PERIOD_LABEL[g.period] && <span>· {PERIOD_LABEL[g.period]}</span>}
              {g.period === "weekly" && scheduledDays.length > 0 && (
                <span>· {scheduledDays.map((day) => day[0].toUpperCase() + day.slice(1)).join(", ")}</span>
              )}
              {hasMissedTask && <span className="font-semibold text-red-600">· Late</span>}
              {g.deadline && <span className="ml-auto">by {formatDateFull(g.deadline)}</span>}
            </div>

            {g.status === "reached" && (
              raiseId === g.id ? (
                <div className="flex items-center gap-1.5 mt-2">
                  <input autoFocus type="number" step="0.01" value={raiseValue}
                    onChange={(e) => setRaiseValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") doRaise(g); if (e.key === "Escape") setRaiseId(null); }}
                    placeholder={`new target > ${g.target}`} className="border rounded px-2 py-0.5 text-xs w-36" />
                  <button onClick={() => doRaise(g)} className="text-xs text-emerald-600 hover:text-emerald-800">raise</button>
                  <button onClick={() => setRaiseId(null)} className="text-xs text-slate-400">cancel</button>
                </div>
              ) : (
                <button onClick={() => { setRaiseId(g.id); setRaiseValue(""); }}
                  className="mt-2 text-xs text-emerald-600 hover:text-emerald-800 border border-emerald-200 rounded px-2 py-1">
                  Raise 🎉
                </button>
              )
            )}

            {manual && (g.history.length >= 2 || g.milestones.length > 0) && (
              <div className="mt-2">
                <button onClick={() => toggleGoal(g.id)}
                  className="text-xs text-slate-400 hover:text-slate-600 underline decoration-dotted">
                  {expanded ? "hide history" : "history"}
                </button>
                {expanded && (
                  <div className="mt-1.5 border-t border-slate-100 pt-1.5 text-xs">
                    <GoalChart history={g.history} milestones={g.milestones} unit={g.unit} />
                    {g.milestones.length > 0 && (
                      <div className="text-slate-500 mt-1">
                        🏅 {g.milestones.map((m) => `${formatValue(m.value, g.unit)} (${formatTimestampDate(m.at)})`).join(" · ")}
                      </div>
                    )}
                    {pace && (
                      <div className="text-slate-500 my-1">
                        pace: {pace.perWeek >= 0 ? "+" : ""}{formatValue(pace.perWeek, g.unit)}/wk
                        {pace.etaWeeks != null && ` · ~${pace.etaWeeks} wk${pace.etaWeeks === 1 ? "" : "s"} to target`}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      {error && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="font-medium text-red-700">Dismiss</button>
        </div>
      )}

      <section className="mb-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 className="font-semibold">Goal checklist</h2>
          <div className="flex rounded border border-slate-200 bg-white p-0.5">
            {(["day", "week", "month"] as const).map((scope) => (
              <button key={scope} type="button" onClick={() => setTaskScope(scope)}
                className={`px-3 py-1 text-sm capitalize ${taskScope === scope ? "bg-slate-900 text-white" : "text-slate-600"}`}>
                {scope}
              </button>
            ))}
          </div>
        </div>
        <GoalTodoWidget scope={taskScope} allowOverdue onChange={loadTasks} />
      </section>

      {/* Add-goal form: fields switch by kind */}
      <form onSubmit={add} className="flex flex-wrap items-end gap-2 mb-5 bg-white p-3 rounded-xl border border-slate-200">
        <label className="flex flex-col text-xs text-slate-500">Type
          <select value={form.kind}
            onChange={(e) => {
              const kind = e.target.value as GoalKind;
              setForm((f) => ({ ...f, kind, period: kind === "spend_cap" ? "monthly" : "once" }));
            }}
            className="border rounded px-2 py-1 text-sm">
            {KINDS.map((k) => <option key={k.value} value={k.value}>{k.icon} {k.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-slate-500">Name
          <input required placeholder="e.g. Emergency fund" value={form.name}
            onChange={(e) => set("name", e.target.value)} className="border rounded px-2 py-1 text-sm w-44" />
        </label>

        {form.kind !== "streak" && (
          <label className="flex flex-col text-xs text-slate-500">Repeats
            <select value={form.period} onChange={(e) => set("period", e.target.value)}
              className="border rounded px-2 py-1 text-sm">
              {form.kind !== "spend_cap" && <option value="once">One-time</option>}
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="interval">Every N days</option>
            </select>
          </label>
        )}

        {form.kind !== "streak" && (
          <label className="flex flex-col text-xs text-slate-500">Target
            <input required type="number" step="0.01" placeholder="Target amount" value={form.target}
              onChange={(e) => set("target", e.target.value)} className="border rounded px-2 py-1 text-sm w-32" />
          </label>
        )}

        {form.kind !== "streak" && form.period === "weekly" && (
          <fieldset className="flex flex-col text-xs text-slate-500">
            <legend>Reminder days</legend>
            <div className="flex gap-1">
              {WEEKDAYS.map((day) => {
                const selected = form.weekly_days.includes(day);
                return <button key={day} type="button" onClick={() => setForm((current) => ({
                  ...current,
                  weekly_days: selected ? current.weekly_days.filter((d) => d !== day) : [...current.weekly_days, day],
                }))} className={`rounded border px-2 py-1 text-xs ${selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-600"}`}>
                  {day.slice(0, 1).toUpperCase()}
                </button>;
              })}
            </div>
          </fieldset>
        )}

        {form.kind !== "streak" && form.period === "interval" && (
          <label className="flex flex-col text-xs text-slate-500">Every
            <span className="flex items-center gap-1">
              <input type="number" min="2" value={form.interval_days} onChange={(e) => set("interval_days", e.target.value)}
                className="w-16 rounded border px-2 py-1 text-sm" /> days
            </span>
          </label>
        )}

        {form.kind !== "streak" && (["daily", "weekly", "interval"] as GoalPeriod[]).includes(form.period) && (
          <label className="flex flex-col text-xs text-slate-500">Reset time
            <input type="time" value={form.reset_time} onChange={(e) => set("reset_time", e.target.value)}
              className="rounded border px-2 py-1 text-sm" />
          </label>
        )}

        {form.kind !== "streak" && form.period === "weekly" && (
          <label className="flex flex-col text-xs text-slate-500">Week resets
            <select value={form.weekly_reset_day} onChange={(e) => set("weekly_reset_day", e.target.value)}
              className="rounded border px-2 py-1 text-sm">
              {WEEKDAYS.map((day) => <option key={day} value={day}>{day[0].toUpperCase() + day.slice(1)}</option>)}
            </select>
          </label>
        )}

        {form.kind !== "streak" && form.period === "monthly" && (
          <label className="flex flex-col text-xs text-slate-500">Resets on day
            <input type="number" min="1" max="28" value={form.monthly_reset_day}
              onChange={(e) => set("monthly_reset_day", e.target.value)} className="w-20 rounded border px-2 py-1 text-sm" />
          </label>
        )}

        {form.kind === "save" && (
          <>
            <label className="flex flex-col text-xs text-slate-500">Track via
              <select value={form.account_id} onChange={(e) => set("account_id", e.target.value)}
                className="border rounded px-2 py-1 text-sm">
                <option value="">— manual —</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </label>
            {!form.account_id && (
              <label className="flex flex-col text-xs text-slate-500">Saved so far
                <input type="number" step="0.01" placeholder="0" value={form.current}
                  onChange={(e) => set("current", e.target.value)} className="border rounded px-2 py-1 text-sm w-28" />
              </label>
            )}
          </>
        )}

        {form.kind === "spend_cap" && (
          <label className="flex flex-col text-xs text-slate-500">Category
            <input required placeholder="e.g. EATING_OUT" value={form.category}
              onChange={(e) => set("category", e.target.value)} className="border rounded px-2 py-1 text-sm w-40" />
          </label>
        )}

        {form.kind === "numeric" && (
          <>
            <label className="flex flex-col text-xs text-slate-500">Goal
              <select value={form.direction} onChange={(e) => set("direction", e.target.value)}
                className="border rounded px-2 py-1 text-sm">
                <option value="reach">Reach target</option>
                <option value="under">Stay under</option>
              </select>
            </label>
            <label className="flex flex-col text-xs text-slate-500">Current value
              <input type="number" step="0.01" placeholder="0" value={form.current}
                onChange={(e) => set("current", e.target.value)} className="border rounded px-2 py-1 text-sm w-28" />
            </label>
          </>
        )}

        {form.kind === "streak" && (
          <>
            <label className="flex flex-col text-xs text-slate-500">Start date
              <input type="date" value={form.since} onChange={(e) => set("since", e.target.value)}
                className="border rounded px-2 py-1 text-sm" />
            </label>
            <label className="flex flex-col text-xs text-slate-500">Milestone (days)
              <input type="number" placeholder="optional" value={form.target}
                onChange={(e) => set("target", e.target.value)} className="border rounded px-2 py-1 text-sm w-28" />
            </label>
          </>
        )}

        {(form.kind === "numeric" || (form.kind === "save" && !form.account_id)) && (
          <label className="flex flex-col text-xs text-slate-500">Step (± buttons)
            <input type="number" step="0.01" value={form.step}
              onChange={(e) => set("step", e.target.value)} className="border rounded px-2 py-1 text-sm w-24" />
          </label>
        )}

        {(form.kind === "save" || form.kind === "numeric") && (
          <label className="flex flex-col text-xs text-slate-500">Target date
            <input type="date" value={form.deadline} onChange={(e) => set("deadline", e.target.value)}
              className="border rounded px-2 py-1 text-sm" />
          </label>
        )}

        <label className="flex flex-col text-xs text-slate-500">Group (optional)
          <input placeholder="e.g. 1000 CLUB" value={form.group}
            onChange={(e) => set("group", e.target.value)} className="border rounded px-2 py-1 text-sm w-36" />
        </label>

        <button className="px-3 py-1.5 rounded bg-slate-900 text-white text-sm">Add goal</button>
      </form>

      {goals.length === 0 && <p className="text-slate-500">No goals yet — add one above.</p>}

      {/* User-named groups first, each with a rolled-up bar. */}
      {[...new Set(goals.filter((g) => g.group).map((g) => g.group as string))].map((name) => {
        const members = goals.filter((g) => g.group === name);
        const agg = groupAggregate(members);
        return (
          <div key={`grp-${name}`} className="mb-5">
            <button onClick={() => toggleCategory(name)}
              title="Show a combined graph of these goals"
              className="w-full flex items-baseline justify-between mb-1 text-left">
              <h3 className="text-sm font-semibold">
                <span className="text-slate-400 mr-1">{expandedGroups.has(name) ? "▾" : "▸"}</span>
                🏷️ {name}
              </h3>
              {agg != null && <span className="text-sm font-semibold text-emerald-600">{agg}%</span>}
            </button>
            {agg != null && (
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-2">
                <div className="h-full bg-emerald-500" style={{ width: `${Math.min(agg, 100)}%` }} />
              </div>
            )}
            {expandedGroups.has(name) && (
              <div className="mb-3 bg-white rounded-xl border border-slate-200 p-3">
                <CategoryChart goals={members} />
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">{members.map((g) => card(g))}</div>
          </div>
        );
      })}

      {/* Ungrouped goals, organized by cadence. Recurring cadences get a rolled-up bar. */}
      {SECTIONS.map((sec) => {
        const inSec = goals.filter((g) => !g.group && sectionOf(g) === sec.key);
        if (inSec.length === 0) return null;
        const agg = ["daily", "weekly", "monthly"].includes(sec.key) ? groupAggregate(inSec) : null;
        return (
          <div key={sec.key} className="mb-5">
            <div className="flex items-baseline justify-between mb-1">
              <h3 className="text-sm font-semibold text-slate-500">{sec.label}</h3>
              {agg != null && <span className="text-sm font-semibold text-emerald-600">{agg}%</span>}
            </div>
            {agg != null && (
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-2">
                <div className="h-full bg-emerald-500" style={{ width: `${Math.min(agg, 100)}%` }} />
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">{inSec.map((g) => card(g))}</div>
          </div>
        );
      })}
    </div>
  );
}
