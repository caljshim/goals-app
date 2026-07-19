export type StaticDashboardWidgetId =
  | "left-to-spend"
  | "monthly-averages"
  | "spending-by-category"
  | "income-vs-expense"
  | "category-transactions"
  | "recent-transactions"
  | "merchant-rules"
  | "manual-transaction"
  | "account-balances"
  | "account-sync"
  | "budget-progress"
  | "budget-form"
  | "goal-todo-day"
  | "goal-todo-week"
  | "goal-todo-month"
  | "portfolio-summary"
  | "portfolio-positions";

export type DashboardWidgetId =
  | StaticDashboardWidgetId
  | `goal:${number}`
  | `goal-name:${string}`
  | `goal-group:${string}`
  | `goal-section:${"daily" | "weekly" | "monthly" | "interval" | "once" | "ongoing"}`;

export type DashboardUiAction =
  | { type: "dashboard.set_widgets"; widget_ids: DashboardWidgetId[] }
  | { type: "dashboard.add_widgets"; widget_ids: DashboardWidgetId[] }
  | { type: "dashboard.remove_widgets"; widget_ids: DashboardWidgetId[] }
  | { type: "dashboard.clear_widgets" }
  | { type: "dashboard.reset_widgets" };

export const DASHBOARD_STORAGE_KEY = "money.dashboard.widgets";
export const DASHBOARD_CHANGED_EVENT = "money-dashboard-widgets-changed";

export const DEFAULT_DASHBOARD_WIDGETS: DashboardWidgetId[] = [
  "left-to-spend",
  "monthly-averages",
  "spending-by-category",
  "portfolio-summary",
];

export const DASHBOARD_WIDGETS: {
  id: StaticDashboardWidgetId;
  label: string;
  source: "Finances" | "Goals" | "Invest";
  description: string;
}[] = [
  { id: "left-to-spend", label: "Left to spend", source: "Finances", description: "Current budget remaining by category." },
  { id: "monthly-averages", label: "Monthly averages", source: "Finances", description: "Average income, expenses, and net over selected months." },
  { id: "spending-by-category", label: "Spending chart", source: "Finances", description: "Current-month spending by category." },
  { id: "income-vs-expense", label: "Income vs expense", source: "Finances", description: "Six-month cash-flow bar chart." },
  { id: "category-transactions", label: "Category transactions", source: "Finances", description: "Merchant groups by spending category." },
  { id: "recent-transactions", label: "Recent transactions", source: "Finances", description: "Latest transaction table with category and amount." },
  { id: "merchant-rules", label: "Merchant rules", source: "Finances", description: "Merchant-to-category automation rules." },
  { id: "manual-transaction", label: "Manual transaction", source: "Finances", description: "Add a manual transaction." },
  { id: "account-balances", label: "Account balances", source: "Finances", description: "Connected account cards and balances." },
  { id: "account-sync", label: "Account sync", source: "Finances", description: "Connect a bank or sync transactions." },
  { id: "budget-progress", label: "Budget progress", source: "Finances", description: "Monthly category budget progress bars." },
  { id: "budget-form", label: "Add budget", source: "Finances", description: "Create a new monthly category budget." },
  { id: "goal-todo-day", label: "Daily to-do list", source: "Goals", description: "Today’s daily goals and recent misses." },
  { id: "goal-todo-week", label: "Weekly to-do list", source: "Goals", description: "Scheduled goals for this and last week." },
  { id: "goal-todo-month", label: "Monthly to-do list", source: "Goals", description: "Monthly goals due this and last month." },
  { id: "portfolio-summary", label: "Portfolio summary", source: "Invest", description: "Account value, cash, and buying power." },
  { id: "portfolio-positions", label: "Portfolio positions", source: "Invest", description: "Open investment positions." },
];

const allowed = new Set(DASHBOARD_WIDGETS.map((w) => w.id));

export function isDashboardWidgetId(id: string): id is DashboardWidgetId {
  if (allowed.has(id as StaticDashboardWidgetId)) return true;
  if (/^goal:\d+$/.test(id)) return true;
  if (/^goal-name:.+/.test(id)) return true;
  if (/^goal-group:.+/.test(id)) return true;
  return /^goal-section:(daily|weekly|monthly|interval|once|ongoing)$/.test(id);
}

export function normalizeDashboardWidgets(ids: unknown): DashboardWidgetId[] {
  if (!Array.isArray(ids)) return [];
  const seen = new Set<DashboardWidgetId>();
  const out: DashboardWidgetId[] = [];
  for (const id of ids) {
    if (typeof id !== "string" || !isDashboardWidgetId(id)) continue;
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

export function readDashboardWidgets(): DashboardWidgetId[] {
  try {
    const raw = localStorage.getItem(DASHBOARD_STORAGE_KEY);
    if (raw === null) return DEFAULT_DASHBOARD_WIDGETS;
    return normalizeDashboardWidgets(JSON.parse(raw));
  } catch {
    return DEFAULT_DASHBOARD_WIDGETS;
  }
}

export function saveDashboardWidgets(ids: DashboardWidgetId[]) {
  localStorage.setItem(DASHBOARD_STORAGE_KEY, JSON.stringify(normalizeDashboardWidgets(ids)));
  window.dispatchEvent(new Event(DASHBOARD_CHANGED_EVENT));
}

export function applyDashboardUiActions(actions: DashboardUiAction[]) {
  let current = readDashboardWidgets();
  for (const action of actions) {
    if (action.type === "dashboard.set_widgets") current = normalizeDashboardWidgets(action.widget_ids);
    if (action.type === "dashboard.add_widgets") {
      const next = normalizeDashboardWidgets(action.widget_ids);
      current = [...current, ...next.filter((id) => !current.includes(id))];
    }
    if (action.type === "dashboard.remove_widgets") {
      const remove = new Set(normalizeDashboardWidgets(action.widget_ids));
      current = current.filter((id) => !remove.has(id));
    }
    if (action.type === "dashboard.clear_widgets") current = [];
    if (action.type === "dashboard.reset_widgets") current = DEFAULT_DASHBOARD_WIDGETS;
  }
  saveDashboardWidgets(current);
}
