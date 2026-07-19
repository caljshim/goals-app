import { useEffect, useState } from "react";
import { api } from "../api";
import { prettifyCategory } from "../format";
import type { MerchantRule } from "../types";

/** Collapsible list of merchant→category rules, with delete. `signal` refetches. */
export default function MerchantRules({
  signal,
  onChange,
}: {
  signal: number;
  onChange?: () => void;
}) {
  const [rules, setRules] = useState<MerchantRule[]>([]);
  const [open, setOpen] = useState(false);

  const load = () => api.getMerchantRules().then(setRules).catch(() => {});
  useEffect(() => { load(); }, [signal]);

  const remove = async (id: number) => {
    await api.deleteMerchantRule(id);
    load();
    onChange?.();
  };

  return (
    <div className="mb-4 bg-white rounded-xl border border-slate-200">
      <button onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-left">
        <span className="text-sm font-medium">
          <span className="text-slate-400 mr-1">{open ? "▾" : "▸"}</span>
          Category rules
          <span className="text-slate-500 font-normal"> · {rules.length}</span>
        </span>
        <span className="text-xs text-slate-400">merchant → category, auto-applied</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          {rules.length === 0 && (
            <p className="text-xs text-slate-500 py-1">
              No rules yet. Recategorizing a transaction below creates one. Or ask the copilot to
              “set up category rules from my history.”
            </p>
          )}
          {rules.map((r) => (
            <div key={r.id} className="flex items-center justify-between gap-2 text-sm py-1 border-t border-slate-50">
              <span className="min-w-0 truncate">
                <span className="text-slate-700">{r.merchant}</span>
                <span className="text-slate-400"> → </span>
                <span className="font-medium">{prettifyCategory(r.category)}</span>
              </span>
              <button onClick={() => remove(r.id)}
                className="text-xs text-slate-400 hover:text-red-500 shrink-0">delete</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
