import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { applyDashboardUiActions, type DashboardUiAction } from "../dashboardConfig";
import type { ChatMessage } from "../types";

type Msg = ChatMessage & { actions?: string[] };

const STARTERS = [
  "How am I doing this month?",
  "What do I own and how risky is it?",
  "How much spare cash could I invest?",
];

export default function CopilotChat({ onApplied }: { onApplied?: () => void }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    setError(null);
    const history: Msg[] = [...messages, { role: "user", content }];
    setMessages(history);
    setInput("");
    setBusy(true);
    try {
      const res = await api.chat(history.map((m) => ({ role: m.role, content: m.content })));
      setMessages([...history, { role: "assistant", content: res.reply || "(no reply)", actions: res.actions }]);
      if (res.ui_actions?.length) applyDashboardUiActions(res.ui_actions as DashboardUiAction[]);
      if (res.refresh) onApplied?.();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Copilot request failed. Please try again.");
      setMessages(history); // keep the user's message; drop the pending assistant turn
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col bg-white rounded-xl border border-slate-200 lg:h-[calc(100vh-8rem)]">
      <div className="px-4 py-3 border-b border-slate-200 font-semibold">✨ Copilot</div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-[16rem]">
        {messages.length === 0 && (
          <div className="text-sm text-slate-500">
            <p className="mb-2">
              Ask about your budgets, spending, portfolio, or where to invest. I coordinate a
              budgeting specialist and an education-first investing specialist — and I can’t place trades.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {STARTERS.map((s) => (
                <button key={s} onClick={() => send(s)}
                  className="px-2 py-1 rounded-full text-xs border border-slate-300 text-slate-600 hover:border-slate-400">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
              m.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-800"
            }`}>
              {m.content}
            </div>
            {m.actions && m.actions.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {m.actions.map((a, j) => (
                  <li key={j} className="text-xs text-emerald-600">✓ {a}</li>
                ))}
              </ul>
            )}
          </div>
        ))}

        {busy && <div className="text-sm text-slate-400">Thinking…</div>}
        <div ref={endRef} />
      </div>

      {error && (
        <div className="mx-3 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="flex gap-2 p-3 border-t border-slate-200">
        <input value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your money…" disabled={busy}
          className="flex-1 border rounded-lg px-3 py-2 text-sm" />
        <button disabled={busy || !input.trim()}
          className="px-3 py-2 rounded-lg bg-slate-900 text-white text-sm disabled:opacity-50">
          Send
        </button>
      </form>
    </div>
  );
}
