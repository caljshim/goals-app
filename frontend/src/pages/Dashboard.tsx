import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import {
  DASHBOARD_CHANGED_EVENT,
  DASHBOARD_WIDGETS,
  DEFAULT_DASHBOARD_WIDGETS,
  readDashboardWidgets,
  saveDashboardWidgets,
  type DashboardWidgetId,
} from "../dashboardConfig";
import { DashboardWidgetContent } from "../components/dashboardWidgets";
import type { Goal } from "../types";

const SECTION_LABEL: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  interval: "Every N days",
  once: "One-time",
  ongoing: "Ongoing",
};

function goalSection(g: Goal): "daily" | "weekly" | "monthly" | "interval" | "once" | "ongoing" {
  return g.kind === "streak" ? "ongoing" : g.period;
}

function widgetMeta(id: DashboardWidgetId, goals: Goal[]) {
  const staticMeta = DASHBOARD_WIDGETS.find((w) => w.id === id);
  if (staticMeta) return staticMeta;
  if (id.startsWith("goal:")) {
    const goal = goals.find((g) => g.id === Number(id.slice("goal:".length)));
    return { id, label: goal?.name ?? `Goal ${id.slice("goal:".length)}`, source: "Goals", description: "Individual goal progress." };
  }
  if (id.startsWith("goal-name:")) {
    return { id, label: id.slice("goal-name:".length), source: "Goals", description: "Individual goal progress." };
  }
  if (id.startsWith("goal-group:")) {
    return { id, label: id.slice("goal-group:".length), source: "Goals", description: "Goal group." };
  }
  const section = id.slice("goal-section:".length);
  return { id, label: SECTION_LABEL[section] ?? section, source: "Goals", description: "Goals by cadence." };
}

type WidgetPickerItem = { id: DashboardWidgetId; label: string; description?: string };
type WidgetPickerGroup = { label: string; items: WidgetPickerItem[] };

function WidgetSelect({ items, active, onAdd }: {
  items: WidgetPickerItem[];
  active: Set<DashboardWidgetId>;
  onAdd: (id: DashboardWidgetId) => void;
}) {
  const available = items.filter((item) => !active.has(item.id));
  const [selected, setSelected] = useState("");

  useEffect(() => {
    if (selected && !available.some((item) => item.id === selected)) setSelected("");
  }, [available, selected]);

  return available.length === 0 ? (
    <p className="text-sm text-slate-500">Everything here is already on the dashboard.</p>
  ) : (
    <div className="flex flex-wrap gap-2">
      <select value={selected} onChange={(e) => setSelected(e.target.value)}
        className="min-w-64 rounded border px-2 py-1 text-sm">
        <option value="">Choose a widget...</option>
        {available.map((item) => (
          <option key={item.id} value={item.id}>{item.label}</option>
        ))}
      </select>
      <button
        onClick={() => {
          if (!selected) return;
          onAdd(selected as DashboardWidgetId);
          setSelected("");
        }}
        disabled={!selected}
        className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-40"
      >
        Add
      </button>
      {selected && (
        <span className="self-center text-xs text-slate-500">
          {available.find((item) => item.id === selected)?.description}
        </span>
      )}
    </div>
  );
}

function WidgetDropdown({ label, groups, active, onAdd }: {
  label: string;
  groups: WidgetPickerGroup[];
  active: Set<DashboardWidgetId>;
  onAdd: (id: DashboardWidgetId) => void;
}) {
  return (
    <details className="rounded-lg border border-slate-200 bg-white">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{label}</summary>
      <div className="grid gap-4 border-t border-slate-100 p-3">
        {groups.map((group) => (
          <div key={group.label}>
            {groups.length > 1 && (
              <h4 className="mb-2 text-xs font-semibold uppercase text-slate-500">{group.label}</h4>
            )}
            <WidgetSelect items={group.items} active={active} onAdd={onAdd} />
          </div>
        ))}
      </div>
    </details>
  );
}

export default function Dashboard() {
  const [widgets, setWidgets] = useState<DashboardWidgetId[]>(readDashboardWidgets);
  const [customizing, setCustomizing] = useState(false);
  const [goals, setGoals] = useState<Goal[]>([]);

  useEffect(() => {
    const reload = () => setWidgets(readDashboardWidgets());
    window.addEventListener(DASHBOARD_CHANGED_EVENT, reload);
    return () => window.removeEventListener(DASHBOARD_CHANGED_EVENT, reload);
  }, []);
  useEffect(() => { api.getGoals().then(setGoals).catch(() => {}); }, []);

  const active = useMemo(() => new Set(widgets), [widgets]);
  const financeItems = DASHBOARD_WIDGETS
    .filter((w) => w.source === "Finances")
    .map((w) => ({ id: w.id, label: w.label, description: w.description }));
  const investItems = DASHBOARD_WIDGETS
    .filter((w) => w.source === "Invest")
    .map((w) => ({ id: w.id, label: w.label, description: w.description }));
  const goalTodoItems = DASHBOARD_WIDGETS
    .filter((w) => w.source === "Goals")
    .map((w) => ({ id: w.id, label: w.label, description: w.description }));
  const goalGroupItems = [...new Set(goals.filter((g) => g.group).map((g) => g.group as string))]
    .sort()
    .map((group) => ({ id: `goal-group:${group}` as DashboardWidgetId, label: group, description: "All goals in this group." }));
  const goalSectionItems = (["daily", "weekly", "monthly", "interval", "once", "ongoing"] as const)
    .filter((section) => goals.some((g) => goalSection(g) === section))
    .map((section) => ({ id: `goal-section:${section}` as DashboardWidgetId, label: SECTION_LABEL[section], description: "All goals in this cadence." }));
  const goalItems = goals
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((g) => ({ id: `goal:${g.id}` as DashboardWidgetId, label: g.name, description: g.group ? `Group: ${g.group}` : "Individual goal." }));

  const commit = (next: DashboardWidgetId[]) => {
    setWidgets(next);
    saveDashboardWidgets(next);
  };
  const addWidget = (id: DashboardWidgetId) => commit([...widgets, id]);
  const removeWidget = (id: DashboardWidgetId) => commit(widgets.filter((w) => w !== id));
  const resetWidgets = () => commit(DEFAULT_DASHBOARD_WIDGETS);
  const moveWidget = (id: DashboardWidgetId, dir: -1 | 1) => {
    const index = widgets.indexOf(id);
    const nextIndex = index + dir;
    if (index < 0 || nextIndex < 0 || nextIndex >= widgets.length) return;
    const next = [...widgets];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    commit(next);
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Dashboard</h2>
          <p className="text-sm text-slate-500">Pick individual widgets from Finances, Goals, and Invest.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setCustomizing((v) => !v)}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
          >
            {customizing ? "Done" : "Customize"}
          </button>
          {customizing && (
            <button
              onClick={resetWidgets}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {customizing && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-3 font-semibold">Add widgets</h3>
          <div className="grid gap-2">
            <WidgetDropdown label="Finances" groups={[{ label: "Finances", items: financeItems }]} active={active} onAdd={addWidget} />
            <WidgetDropdown label="Invest" groups={[{ label: "Invest", items: investItems }]} active={active} onAdd={addWidget} />
            <WidgetDropdown
              label="Goals"
              groups={[
                { label: "To-do lists", items: goalTodoItems },
                { label: "Groups / categories", items: goalGroupItems },
                { label: "Cadence", items: goalSectionItems },
                { label: "Individual goals", items: goalItems },
              ]}
              active={active}
              onAdd={addWidget}
            />
          </div>
        </div>
      )}

      {widgets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
          Your dashboard is empty. Turn on Customize or ask Copilot to add dashboard widgets.
        </div>
      ) : (
        widgets.map((id, index) => {
          const meta = widgetMeta(id, goals);
          return (
            <section key={id} className="border-t border-slate-200 pt-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="text-xs font-medium uppercase text-slate-400">{meta.source}</span>
                  <h3 className="font-semibold">{meta.label}</h3>
                </div>
                {customizing && (
                  <div className="flex gap-1">
                    <button onClick={() => moveWidget(id, -1)} disabled={index === 0}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 disabled:opacity-40">
                      Up
                    </button>
                    <button onClick={() => moveWidget(id, 1)} disabled={index === widgets.length - 1}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 disabled:opacity-40">
                      Down
                    </button>
                    <button onClick={() => removeWidget(id)}
                      className="rounded border border-red-200 bg-white px-2 py-1 text-xs text-red-600">
                      Remove
                    </button>
                  </div>
                )}
              </div>
              <DashboardWidgetContent id={id} onChange={() => setWidgets(readDashboardWidgets())} />
            </section>
          );
        })
      )}
    </div>
  );
}
