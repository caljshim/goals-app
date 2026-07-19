import axios from "axios";
import type { Account, Budget, ChatMessage, ChatResponse, Goal, GoalTask, MerchantRule, Portfolio, Summary, Transaction } from "./types";

const http = axios.create({ baseURL: "/api" });

export const api = {
  getAccounts: () => http.get<Account[]>("/accounts").then((r) => r.data),
  getTransactions: (params: Record<string, string> = {}) =>
    http.get<Transaction[]>("/transactions", { params }).then((r) => r.data),
  createTransaction: (body: Partial<Transaction>) =>
    http.post<Transaction>("/transactions", body).then((r) => r.data),
  updateTransaction: (id: number, user_category: string | null) =>
    http.patch<Transaction>(`/transactions/${id}`, { user_category }).then((r) => r.data),
  // Rule by default: apply a category to this transaction's whole merchant (past & future).
  setMerchantCategory: (id: number, category: string) =>
    http.patch<Transaction>(`/transactions/${id}/merchant-category`, { category }).then((r) => r.data),
  getMerchantRules: () => http.get<MerchantRule[]>("/merchant-rules").then((r) => r.data),
  createMerchantRule: (merchant: string, category: string) =>
    http.post<MerchantRule>("/merchant-rules", { merchant, category }).then((r) => r.data),
  deleteMerchantRule: (id: number) => http.delete(`/merchant-rules/${id}`),
  // Link an incoming reimbursement (e.g. a Zelle in) to the expense it pays back;
  // target_id=null unlinks it.
  linkReimbursement: (id: number, target_id: number | null) =>
    http.patch<Transaction>(`/transactions/${id}/reimburses`, { target_id }).then((r) => r.data),
  deleteTransaction: (id: number) => http.delete(`/transactions/${id}`),
  getBudgets: () => http.get<Budget[]>("/budgets").then((r) => r.data),
  createBudget: (category: string, monthly_limit: number) =>
    http.post<Budget>("/budgets", { category, monthly_limit }).then((r) => r.data),
  updateBudget: (id: number, monthly_limit: number) =>
    http.patch<Budget>(`/budgets/${id}`, { monthly_limit }).then((r) => r.data),
  deleteBudget: (id: number) => http.delete(`/budgets/${id}`),
  getSummary: (month: string) =>
    http.get<Summary>("/dashboard/summary", { params: { month } }).then((r) => r.data),
  createLinkToken: () =>
    http.post<{ link_token: string }>("/plaid/link-token").then((r) => r.data.link_token),
  exchangePublicToken: (public_token: string) =>
    http.post("/plaid/exchange", { public_token }).then((r) => r.data),
  sync: () => http.post("/plaid/sync").then((r) => r.data),
  refreshBank: () => http.post("/plaid/refresh").then((r) => r.data),
  getGoals: () => http.get<Goal[]>("/goals").then((r) => r.data),
  getGoalTasks: (scope: "day" | "week" | "month") =>
    http.get<GoalTask[]>("/goal-tasks", { params: { scope } }).then((r) => r.data),
  setGoalCheckin: (id: number, scheduled_for: string, completed: boolean, allow_overdue = false) =>
    http.patch<GoalTask>(`/goals/${id}/checkin`, { scheduled_for, completed, allow_overdue }).then((r) => r.data),
  createGoal: (body: Record<string, unknown>) =>
    http.post<Goal>("/goals", body).then((r) => r.data),
  updateGoal: (id: number, body: Record<string, unknown>) =>
    http.patch<Goal>(`/goals/${id}`, body).then((r) => r.data),
  setGoalProgress: (id: number, body: { current?: number; add?: number }) =>
    http.patch<Goal>(`/goals/${id}/progress`, body).then((r) => r.data),
  resetGoal: (id: number) => http.post<Goal>(`/goals/${id}/reset`).then((r) => r.data),
  raiseGoal: (id: number, target: number) =>
    http.post<Goal>(`/goals/${id}/raise`, { target }).then((r) => r.data),
  deleteGoal: (id: number) => http.delete(`/goals/${id}`),
  getPortfolio: () => http.get<Portfolio>("/portfolio").then((r) => r.data),
  chat: (messages: ChatMessage[]) =>
    http.post<ChatResponse>("/assistant/chat", { messages }).then((r) => r.data),
};
