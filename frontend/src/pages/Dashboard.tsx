import { useEffect, useMemo, useState, type DragEvent } from "react";
import { api } from "../api";
import {
  DASHBOARD_CHANGED_EVENT,
  DASHBOARD_WIDGETS,
  DEFAULT_DASHBOARD_WIDGETS,
  readDashboardWidgets,
  reorderWidgets,
  saveDashboardWidgets,
  type DashboardWidgetId,
} from "../dashboardConfig";
import { DashboardWidgetContent } from "../components/dashboardWidgets";
import { isRoutine } from "../goals";
import type { Goal } from "../types";

function GripIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
      <circle cx="5.5" cy="3.5" r="1.4" /><circle cx="10.5" cy="3.5" r="1.4" />
      <circle cx="5.5" cy="8" r="1.4" /><circle cx="10.5" cy="8" r="1.4" />
      <circle cx="5.5" cy="12.5" r="1.4" /><circle cx="10.5" cy="12.5" r="1.4" />
    </svg>
  );
}

function ChevronIcon({ dir }: { dir: "up" | "down" }) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      style={dir === "down" ? { transform: "rotate(180deg)" } : undefined}>
      <path d="M4 10l4-4 4 4" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

function DropLine({ atBottom = false }: { atBottom?: boolean }) {
  return (
    <span
      className={`pointer-events-none absolute inset-x-3 z-10 flex items-center ${atBottom ? "-bottom-2.5" : "-top-2.5"}`}
      aria-hidden="true"
    >
      <span className="h-2 w-2 rounded-full bg-indigo-500" />
      <span className="h-0.5 flex-1 rounded-full bg-indigo-500" />
    </span>
  );
}

const SECTION_LABEL: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  interval: "Every N days",
  once: "One-time",
  ongoing: "Streaks",
};

function goalSection(g: Goal): "daily" | "weekly" | "monthly" | "interval" | "once" | "ongoing" {
  return g.kind === "streak" ? "ongoing" : g.period;
}

function widgetMeta(id: DashboardWidgetId, goals: Goal[]) {
  const staticMeta = DASHBOARD_WIDGETS.find((w) => w.id === id);
  if (staticMeta) return staticMeta;
  if (id.startsWith("goal:")) {
    const goal = goals.find((g) => g.id === Number(id.slice("goal:".length)));
    return { id, label: goal?.name ?? `Goal ${id.slice("goal:".length)}`, source: goal && isRoutine(goal) ? "Schedule" : "Goals", description: "Individual progress." };
  }
  if (id.startsWith("goal-name:")) {
    return { id, label: id.slice("goal-name:".length), source: "Goals", description: "Individual goal progress." };
  }
  if (id.startsWith("goal-group:")) {
    return { id, label: id.slice("goal-group:".length), source: "Goals", description: "Goal group." };
  }
  if (id.startsWith("routine-group:")) {
    return { id, label: id.slice("routine-group:".length), source: "Schedule", description: "Routine group." };
  }
  if (id.startsWith("routine-section:")) {
    const section = id.slice("routine-section:".length);
    return { id, label: SECTION_LABEL[section] ?? section, source: "Schedule", description: "Routines by cadence." };
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
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

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
  const scheduleWidgetItems = DASHBOARD_WIDGETS
    .filter((w) => w.source === "Schedule")
    .map((w) => ({ id: w.id, label: w.label, description: w.description }));
  const goalGroupItems = [...new Set(goals.filter((g) => !isRoutine(g) && g.group).map((g) => g.group as string))]
    .sort()
    .map((group) => ({ id: `goal-group:${group}` as DashboardWidgetId, label: group, description: "All goals in this group." }));
  const routineGroupItems = [...new Set(goals.filter((g) => isRoutine(g) && g.group).map((g) => g.group as string))]
    .sort()
    .map((group) => ({ id: `routine-group:${group}` as DashboardWidgetId, label: group, description: "All routines in this group." }));
  const goalSectionItems = (["once", "ongoing"] as const)
    .filter((section) => goals.some((g) => !isRoutine(g) && goalSection(g) === section))
    .map((section) => ({ id: `goal-section:${section}` as DashboardWidgetId, label: SECTION_LABEL[section], description: "All goals in this cadence." }));
  const routineSectionItems = (["daily", "weekly", "monthly", "interval"] as const)
    .filter((section) => goals.some((g) => isRoutine(g) && goalSection(g) === section))
    .map((section) => ({ id: `routine-section:${section}` as DashboardWidgetId, label: SECTION_LABEL[section], description: "All routines in this cadence." }));
  const goalItems = goals.filter((g) => !isRoutine(g))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((g) => ({ id: `goal:${g.id}` as DashboardWidgetId, label: g.name, description: g.group ? `Group: ${g.group}` : "Individual goal." }));
  const routineItems = goals.filter(isRoutine)
    .slice().sort((a, b) => a.name.localeCompare(b.name))
    .map((g) => ({ id: `goal:${g.id}` as DashboardWidgetId, label: g.name, description: g.group ? `Group: ${g.group}` : "Individual routine." }));

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

  const endDrag = () => {
    setDragIndex(null);
    setDropIndex(null);
  };
  const handleDragStart = (index: number) => (e: DragEvent<HTMLElement>) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index)); // Firefox needs a payload
    const card = (e.currentTarget as HTMLElement).closest<HTMLElement>("[data-widget-card]");
    if (card) {
      const rect = card.getBoundingClientRect();
      e.dataTransfer.setDragImage(card, e.clientX - rect.left, e.clientY - rect.top);
    }
  };
  const handleDragOver = (index: number) => (e: DragEvent<HTMLElement>) => {
    if (dragIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = e.currentTarget.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    setDropIndex(after ? index + 1 : index);
  };
  const handleDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    if (dragIndex !== null && dropIndex !== null) {
      commit(reorderWidgets(widgets, dragIndex, dropIndex));
    }
    endDrag();
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Dashboard</h2>
          <p className="text-sm text-slate-500">Pick individual widgets from Finances, Goals, Schedule, and Invest.</p>
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
            <WidgetDropdown
              label="Goals"
              groups={[
                { label: "Groups / categories", items: goalGroupItems },
                { label: "Cadence", items: goalSectionItems },
                { label: "Individual goals", items: goalItems },
              ]}
              active={active}
              onAdd={addWidget}
            />
            <WidgetDropdown
              label="Schedule"
              groups={[
                { label: "Calendar / agenda", items: scheduleWidgetItems },
                { label: "Groups / categories", items: routineGroupItems },
                { label: "Cadence", items: routineSectionItems },
                { label: "Individual routines", items: routineItems },
              ]}
              active={active}
              onAdd={addWidget}
            />
            <WidgetDropdown label="Invest" groups={[{ label: "Invest", items: investItems }]} active={active} onAdd={addWidget} />
          </div>
        </div>
      )}

      {customizing && widgets.length > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-slate-500">
          <span className="text-slate-400"><GripIcon /></span>
          Drag a card by its handle to reorder, or use the arrows.
        </p>
      )}

      {widgets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
          Your dashboard is empty. Turn on Customize or ask Audel to add dashboard widgets.
        </div>
      ) : (
        widgets.map((id, index) => {
          const meta = widgetMeta(id, goals);
          const isDragging = dragIndex === index;
          const isLast = index === widgets.length - 1;
          return (
            <section
              key={id}
              data-widget-card
              onDragOver={customizing ? handleDragOver(index) : undefined}
              onDrop={customizing ? handleDrop : undefined}
              className={
                customizing
                  ? `relative rounded-xl border bg-white p-4 transition-[opacity,box-shadow] motion-reduce:transition-none ${
                      isDragging ? "opacity-40 ring-2 ring-indigo-300" : "border-slate-200"
                    }`
                  : "border-t border-slate-200 pt-4"
              }
            >
              {customizing && dragIndex !== null && dropIndex === index && <DropLine />}
              {customizing && dragIndex !== null && isLast && dropIndex === widgets.length && <DropLine atBottom />}
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  {customizing && (
                    <span
                      draggable
                      onDragStart={handleDragStart(index)}
                      onDragEnd={endDrag}
                      aria-label={`Drag ${meta.label} to reorder`}
                      className="flex shrink-0 cursor-grab touch-none items-center rounded-md px-1 py-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing"
                    >
                      <GripIcon />
                    </span>
                  )}
                  <div className="min-w-0">
                    <span className="text-xs font-medium uppercase text-slate-400">{meta.source}</span>
                    <h3 className="truncate font-semibold">{meta.label}</h3>
                  </div>
                </div>
                {customizing && (
                  <div className="flex shrink-0 items-center gap-1">
                    <button onClick={() => moveWidget(id, -1)} disabled={index === 0} aria-label="Move up"
                      className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-30">
                      <ChevronIcon dir="up" />
                    </button>
                    <button onClick={() => moveWidget(id, 1)} disabled={isLast} aria-label="Move down"
                      className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-30">
                      <ChevronIcon dir="down" />
                    </button>
                    <button onClick={() => removeWidget(id)} aria-label={`Remove ${meta.label}`}
                      className="ml-1 rounded-md border border-slate-200 bg-white p-1.5 text-slate-400 hover:border-red-200 hover:bg-red-50 hover:text-red-600">
                      <CloseIcon />
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
