export interface Account {
  id: number; item_id: number; plaid_account_id: string; persistent_account_id?: string | null;
  name: string; official_name: string | null;
  type: string; subtype: string | null; mask: string | null;
  current_balance: number | null; available_balance: number | null; currency: string;
}
export interface Transaction {
  id: number; account_id: number; date: string; name: string; merchant_name: string | null;
  amount: number; category: string | null; user_category: string | null;
  effective_category: string; pending: boolean; is_manual: boolean;
  reimburses_transaction_id: number | null;
  reimbursement_category: string | null;
  is_budgeted: boolean | null;
}
export type BudgetPeriod = "daily" | "weekly" | "monthly";
export interface Budget { id: number; category: string; monthly_limit: number; period: BudgetPeriod; }
export interface MerchantRule { id: number; merchant: string; category: string; }
export type GoalKind = "save" | "spend_cap" | "financial" | "numeric" | "streak";
export type FinancialMetric = "account_balance" | "category_spend" | "debt_balance" | "net_worth" | "income" | "cash_flow";
export type FinancialRule = "reach" | "stay_under" | "reduce_to";
export type FinancialSource = "accounts" | "manual";
export type GoalPeriod = "once" | "daily" | "weekly" | "monthly" | "interval";
export type GoalDirection = "reach" | "under";
export type Weekday = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
export interface Goal {
  id: number; name: string; kind: GoalKind; period: GoalPeriod; direction: GoalDirection; step: number;
  target: number | null; account_id: number | null; category: string | null;
  account_ids?: number[]; financial_metric?: FinancialMetric | null; financial_rule?: FinancialRule | null;
  financial_source?: FinancialSource | null;
  current: number | null; since: string | null; deadline: string | null;
  group: string | null; weekly_day?: Weekday | null; weekly_days?: Weekday[];
  reminder_time?: string | null;
  reset_time?: string; weekly_reset_day?: Weekday; monthly_reset_day?: number; interval_days?: number | null;
  // computed at read time by the backend goal type
  current_value: number; anchor_value?: number | null; pct: number | null; status: string; unit: string;
  linked_label: string | null; days: number | null; best_days: number | null;
  weekly_streak?: number;
  history: { value: number; at: string }[];
  milestones: { value: number; at: string }[];
}
export interface BudgetProgress {
  budget_id: number; category: string; period: BudgetPeriod; window_start: string; window_end: string;
  limit: number; spent: number; remaining: number; pct: number;
}
export interface Summary {
  spending_by_category: { category: string; total: number }[];
  income_total: number; expense_total: number; net: number;
  monthly_trend: { month: string; income: number; expense: number }[];
  budget_progress: BudgetProgress[];
  complete_months: string[];
}
export interface ChatMessage { role: "user" | "assistant"; content: string; }
export interface DashboardUiAction {
  type: "dashboard.set_widgets" | "dashboard.add_widgets" | "dashboard.remove_widgets" | "dashboard.clear_widgets" | "dashboard.reset_widgets";
  widget_ids?: string[];
}
export interface GoalTask {
  goal_id: number; name: string; period: "daily" | "weekly" | "monthly";
  scheduled_for: string; completed: boolean; missed: boolean; reminder_time?: string | null;
}
export interface Reminder {
  id: number; title: string; scheduled_for: string; reminder_time: string | null;
  notes: string | null; completed: boolean; created_at: string;
  repeat_until_completed: boolean; nudge_interval_minutes: number | null;
}
export interface CalendarEvent {
  id: number; title: string; scheduled_for: string;
  start_time: string | null; end_time: string | null;
  location: string | null; notes: string | null; created_at: string;
}
export interface ScheduleItem {
  id: string; source: "event" | "reminder" | "routine" | "goal_deadline"; source_id: number;
  title: string; scheduled_for: string; reminder_time: string | null;
  completed: boolean; missed: boolean; notes: string | null; period: GoalPeriod | null;
  repeat_until_completed: boolean; nudge_interval_minutes: number | null;
  end_time: string | null; location: string | null;
}
export interface ChatResponse { reply: string; actions: string[]; refresh: boolean; ui_actions?: DashboardUiAction[]; }

// --- investing (tastytrade portfolio) ---
export interface Position {
  symbol: string;
  underlying_symbol: string;
  instrument_type: string;
  quantity: number;
  average_open_price: number | null;
  price: number;
  multiplier: number;
  market_value: number;
  expires_at: string | null;
}
export interface PortfolioAccount {
  account_number: string;
  nickname: string | null;
  type: string;
  net_liquidating_value: number | null;
  cash_balance: number | null;
  equity_buying_power: number | null;
  derivative_buying_power: number | null;
  maintenance_excess: number | null;
  positions: Position[];
}
export interface Portfolio {
  environment: string;
  accounts: PortfolioAccount[];
}
