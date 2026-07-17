import axios from "axios";
import type { Account, Budget, ChatMessage, ChatResponse, Portfolio, Summary, Transaction } from "./types";

const http = axios.create({ baseURL: "/api" });

export const api = {
  getAccounts: () => http.get<Account[]>("/accounts").then((r) => r.data),
  getTransactions: (params: Record<string, string> = {}) =>
    http.get<Transaction[]>("/transactions", { params }).then((r) => r.data),
  createTransaction: (body: Partial<Transaction>) =>
    http.post<Transaction>("/transactions", body).then((r) => r.data),
  updateTransaction: (id: number, user_category: string | null) =>
    http.patch<Transaction>(`/transactions/${id}`, { user_category }).then((r) => r.data),
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
  getPortfolio: () => http.get<Portfolio>("/portfolio").then((r) => r.data),
  chat: (messages: ChatMessage[]) =>
    http.post<ChatResponse>("/assistant/chat", { messages }).then((r) => r.data),
};
