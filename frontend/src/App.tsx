import { useEffect, useState } from "react";
import { api } from "./api";
import CopilotChat from "./components/CopilotChat";
import P2PReviewCard from "./components/P2PReviewCard";
import Portfolio from "./components/Portfolio";
import Accounts from "./pages/Accounts";
import Budgets from "./pages/Budgets";
import Dashboard from "./pages/Dashboard";
import Transactions from "./pages/Transactions";

const TABS = ["Dashboard", "Transactions", "Accounts", "Budgets", "Invest"] as const;
type Tab = (typeof TABS)[number];

const SYNC_INTERVAL_MS = 15 * 60 * 1000;

export default function App() {
  const [tab, setTab] = useState<Tab>("Dashboard");
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  // On-demand: ask Plaid to re-pull the bank NOW (e.g. payday), then ingest.
  // Plaid fetches asynchronously, so wait a beat before syncing; the 15-min
  // auto-sync catches anything that takes longer.
  const refreshNow = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(null);
    try {
      await api.refreshBank();
      await new Promise((r) => setTimeout(r, 8000));
      await api.sync();
      setRefreshKey((k) => k + 1);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setRefreshError(typeof detail === "string" ? detail : "Refresh failed. Please try again.");
    } finally {
      setRefreshing(false);
    }
  };

  // Pull fresh bank data on open and every 15 min (banks only post a few times a
  // day, so faster polling buys nothing). Only remount pages when something changed.
  useEffect(() => {
    let cancelled = false;
    const doSync = async () => {
      try {
        const t = await api.sync();
        if (!cancelled && (t.added || t.modified || t.removed)) setRefreshKey((k) => k + 1);
      } catch {
        // sync unavailable (e.g. Plaid keys not configured) — stay on local data
      }
    };
    doSync();
    const id = setInterval(doSync, SYNC_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return (
    <div className="max-w-7xl mx-auto p-4 lg:p-6">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h1 className="text-2xl font-bold">💰 Money</h1>
        <div className="flex items-center gap-2">
          {refreshError && <span className="text-xs text-red-600">{refreshError}</span>}
          <button
            onClick={refreshNow}
            disabled={refreshing}
            title="Ask Plaid to re-pull your bank right now (may incur a small Plaid fee)"
            className="px-3 py-1.5 rounded-lg text-sm border border-slate-300 bg-white text-slate-600 hover:border-slate-400 disabled:opacity-60"
          >
            {refreshing ? "Refreshing…" : "⟳ Refresh from bank"}
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <div className="min-w-0 flex-1">
          <nav className="flex gap-2 mb-6">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 rounded-lg text-sm font-medium ${
                  tab === t ? "bg-slate-900 text-white" : "bg-white border border-slate-200"
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
          {/* Remount the active page when the assistant changes data so it refetches. */}
          <div key={refreshKey}>
            {tab === "Dashboard" && <Dashboard />}
            {tab === "Transactions" && <Transactions />}
            {tab === "Accounts" && <Accounts />}
            {tab === "Budgets" && <Budgets />}
            {tab === "Invest" && <Portfolio />}
          </div>
        </div>
        <aside className="w-full lg:w-96 shrink-0 lg:sticky lg:top-6">
          <CopilotChat onApplied={() => setRefreshKey((k) => k + 1)} />
        </aside>
      </div>
      <P2PReviewCard refreshSignal={refreshKey} onChange={() => setRefreshKey((k) => k + 1)} />
    </div>
  );
}
