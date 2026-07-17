export interface Account {
  id: number; plaid_account_id: string; name: string; official_name: string | null;
  type: string; subtype: string | null; mask: string | null;
  current_balance: number | null; available_balance: number | null; currency: string;
}
export interface Transaction {
  id: number; account_id: number; date: string; name: string; merchant_name: string | null;
  amount: number; category: string | null; user_category: string | null;
  effective_category: string; pending: boolean; is_manual: boolean;
}
export interface Budget { id: number; category: string; monthly_limit: number; }
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
export interface ChatResponse { reply: string; actions: string[]; refresh: boolean; }

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
