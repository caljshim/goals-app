import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import FinanceOverview from "../components/FinanceOverview";
import { localMonthKey, unbudgetedTransactions } from "../unbudgeted";
import type { Transaction } from "../types";
import Accounts from "./Accounts";
import Budgets from "./Budgets";
import Transactions from "./Transactions";

const FINANCE_TABS = ["Overview", "Transactions", "Accounts", "Budgets"] as const;
type FinanceTab = (typeof FINANCE_TABS)[number];

export default function Finances() {
  const [tab, setTab] = useState<FinanceTab>("Overview");
  const [unbudgetedCount, setUnbudgetedCount] = useState(0);

  const updateUnbudgetedCount = useCallback((transactions: Transaction[]) => {
    setUnbudgetedCount(unbudgetedTransactions(transactions, localMonthKey()).length);
  }, []);

  useEffect(() => {
    api.getTransactions().then(updateUnbudgetedCount).catch(() => {});
  }, [tab, updateUnbudgetedCount]);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Finances</h2>
          <p className="text-sm text-slate-500">Cash flow, transactions, accounts, and budgets.</p>
        </div>
        <nav className="flex flex-wrap gap-2">
          {FINANCE_TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                tab === t ? "bg-slate-900 text-white" : "border border-slate-200 bg-white"
              }`}
            >
              {t}
              {t === "Transactions" && unbudgetedCount > 0 && (
                <span className="ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full bg-amber-400 px-1.5 py-0.5 text-[10px] font-bold leading-none text-amber-950">
                  {unbudgetedCount}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {tab === "Overview" && (
        <FinanceOverview
          onOpenTransactions={() => setTab("Transactions")}
          onTransactionsChange={updateUnbudgetedCount}
        />
      )}
      {tab === "Transactions" && <Transactions onTransactionsChange={updateUnbudgetedCount} />}
      {tab === "Accounts" && <Accounts />}
      {tab === "Budgets" && <Budgets />}
    </div>
  );
}
