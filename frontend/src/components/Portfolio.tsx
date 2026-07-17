import { useEffect, useState } from "react";
import { api } from "../api";
import type { Portfolio as PortfolioData } from "../types";

const usd = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function Portfolio() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getPortfolio()
      .then(setData)
      .catch((e) => {
        const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Failed to load portfolio.");
      });
  }, []);

  if (error) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
        <p className="font-semibold mb-1">Portfolio unavailable</p>
        <p>{error}</p>
        <p className="mt-2 text-amber-700">
          Set up a tastytrade account at developer.tastytrade.com, then put the OAuth
          credentials in <code>backend/.env</code> and restart the backend.
        </p>
      </div>
    );
  }
  if (!data) return <p className="text-slate-500">Loading portfolio…</p>;

  return (
    <div className="grid gap-4">
      {data.environment !== "prod" && (
        <div className="text-xs text-slate-500 bg-slate-100 rounded-lg px-3 py-1.5 w-fit">
          🧪 Sandbox environment — fake money
        </div>
      )}
      {data.accounts.map((a) => (
        <div key={a.account_number} className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="font-semibold">
              {a.nickname || a.account_number}
              <span className="ml-2 text-xs font-normal text-slate-400">{a.type}</span>
            </h3>
            <span className="text-xl font-bold">{usd(a.net_liquidating_value)}</span>
          </div>
          <div className="grid grid-cols-3 gap-3 text-sm mb-4">
            <div><div className="text-slate-500 text-xs">Cash</div>{usd(a.cash_balance)}</div>
            <div><div className="text-slate-500 text-xs">Stock buying power</div>{usd(a.equity_buying_power)}</div>
            <div><div className="text-slate-500 text-xs">Options buying power</div>{usd(a.derivative_buying_power)}</div>
          </div>
          {a.positions.length === 0 ? (
            <p className="text-sm text-slate-500">No open positions.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr>
                  <th className="py-1">Symbol</th><th className="py-1">Type</th>
                  <th className="py-1 text-right">Qty</th><th className="py-1 text-right">Avg open</th>
                  <th className="py-1 text-right">Price</th><th className="py-1 text-right">Value</th>
                </tr>
              </thead>
              <tbody>
                {a.positions.map((p) => (
                  <tr key={p.symbol} className="border-t border-slate-100">
                    <td className="py-1.5 font-medium">{p.symbol}</td>
                    <td className="py-1.5 text-slate-500">{p.instrument_type}</td>
                    <td className="py-1.5 text-right">{p.quantity}</td>
                    <td className="py-1.5 text-right">{usd(p.average_open_price)}</td>
                    <td className="py-1.5 text-right">{usd(p.price)}</td>
                    <td className="py-1.5 text-right">{usd(p.market_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}
