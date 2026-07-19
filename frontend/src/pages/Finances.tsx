import { useState } from "react";
import FinanceOverview from "../components/FinanceOverview";
import Accounts from "./Accounts";
import Budgets from "./Budgets";
import Transactions from "./Transactions";

const FINANCE_TABS = ["Overview", "Transactions", "Accounts", "Budgets"] as const;
type FinanceTab = (typeof FINANCE_TABS)[number];

export default function Finances() {
  const [tab, setTab] = useState<FinanceTab>("Overview");

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
            </button>
          ))}
        </nav>
      </div>

      {tab === "Overview" && <FinanceOverview />}
      {tab === "Transactions" && <Transactions />}
      {tab === "Accounts" && <Accounts />}
      {tab === "Budgets" && <Budgets />}
    </div>
  );
}
