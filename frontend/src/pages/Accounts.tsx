import { useEffect, useState } from "react";
import { api } from "../api";
import PlaidLinkButton from "../components/PlaidLinkButton";
import { formatCurrency, prettifyCategory } from "../format";
import type { Account } from "../types";

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const data = await api.getAccounts();
      setAccounts(data);
    } catch {
      setError("Failed to load accounts. Please try again.");
    }
  };
  useEffect(() => { load(); }, []);

  const doSync = async () => {
    setSyncing(true);
    try {
      await api.sync();
      await load();
    } catch {
      setError("Failed to sync transactions. Please try again.");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div>
      {error && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="font-medium text-red-700">Dismiss</button>
        </div>
      )}
      <div className="flex gap-2 mb-4">
        <PlaidLinkButton onLinked={load} onError={setError} />
        <button onClick={doSync} disabled={syncing}
          className="px-4 py-2 rounded-lg bg-white border border-slate-200 text-sm font-medium disabled:opacity-50">
          {syncing ? "Syncing…" : "Sync transactions"}
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {accounts.map((a) => (
          <div key={a.id} className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-sm text-slate-500">{prettifyCategory(a.subtype ?? a.type)} ••{a.mask}</div>
            <div className="font-semibold">{a.name}</div>
            <div className="text-2xl font-bold mt-1">
              {a.current_balance != null ? formatCurrency(a.current_balance) : "—"}
            </div>
          </div>
        ))}
        {accounts.length === 0 && <p className="text-slate-500">No accounts yet. Connect a bank to start.</p>}
      </div>
    </div>
  );
}
