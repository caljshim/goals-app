export interface Account {
  id: number; plaid_account_id: string; name: string; official_name: string | null;
  type: string; subtype: string | null; mask: string | null;
  current_balance: number | null; available_balance: number | null; currency: string;
}
export interface Transaction {
  id: number; account_id: number; date: string; name: string; merchant_name: string | null;
  amount: number; category: string | null; user_category: string | null;
  effective_category: string; pending: boolean; is_manual: boolean;
  reimburses_transaction_id: number | null;
}
export interface Budget { id: number; category: string; monthly_limit: number; }
export interface MerchantRule { id: number; merchant: string; category: string; }
export type GoalKind = "save" | "spend_cap" | "numeric" | "streak";
export type GoalPeriod = "once" | "daily" | "weekly" | "monthly" | "interval";
export type GoalDirection = "reach" | "under";
export type Weekday = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
export interface Goal {
  id: number; name: string; kind: GoalKind; period: GoalPeriod; direction: GoalDirection; step: number;
  target: number | null; account_id: number | null; category: string | null;
  current: number | null; since: string | null; deadline: string | null;
  group: string | null; weekly_day?: Weekday | null; weekly_days?: Weekday[];
  reset_time?: string; weekly_reset_day?: Weekday; monthly_reset_day?: number; interval_days?: number | null;
  // computed at read time by the backend goal type
  current_value: number; pct: number | null; status: string; unit: string;
  linked_label: string | null; days: number | null; best_days: number | null;
  history: { value: number; at: string }[];
  milestones: { value: number; at: string }[];
}
export interface BudgetProgress {
  category: string; limit: number; spent: number; remaining: number; pct: number;
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
  scheduled_for: string; completed: boolean; missed: boolean;
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
