import { useState } from "react";
import { formatCurrency, formatDateFull, prettifyCategory } from "../format";
import { candidateExpenses } from "../zelle";
import type { Transaction } from "../types";

/** Inline searchable list of expenses an incoming reimbursement can be linked to. */
export default function ExpensePicker({
  expenses,
  onPick,
  onCancel,
}: {
  expenses: Transaction[];
  onPick: (id: number) => void;
  onCancel: () => void;
}) {
  const [q, setQ] = useState("");
  const list = candidateExpenses(expenses, q).slice(0, 12);

  return (
    <div className="mt-1 border border-slate-200 rounded-lg p-2 bg-slate-50">
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search an expense to reimburse…"
        className="border rounded px-1 py-0.5 w-full mb-1 text-xs"
      />
      <div className="max-h-40 overflow-y-auto space-y-0.5">
        {list.map((e) => (
          <button
            key={e.id}
            onClick={() => onPick(e.id)}
            className="w-full flex items-center justify-between gap-2 text-left px-1 py-0.5 rounded hover:bg-white"
          >
            <span className="min-w-0 truncate">
              {e.merchant_name ?? e.name}
              <span className="text-slate-400"> · {prettifyCategory(e.effective_category)}</span>
            </span>
            <span className="text-slate-400 shrink-0">{formatDateFull(e.date)} · {formatCurrency(e.amount)}</span>
          </button>
        ))}
        {list.length === 0 && <div className="text-slate-400 px-1 py-0.5">No matching expenses.</div>}
      </div>
      <div className="text-right pt-1">
        <button onClick={onCancel} className="text-slate-500 hover:text-slate-700">Cancel</button>
      </div>
    </div>
  );
}
