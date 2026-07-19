import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { branchConversation, type CopilotMessage } from "../copilotConversation";
import { applyDashboardUiActions, type DashboardUiAction } from "../dashboardConfig";
import { parseCopilotContent, parseInlineMarkdown } from "../inlineMarkdown";

const STARTERS = [
  "How am I doing this month?",
  "What do I own and how risky is it?",
  "How much spare cash could I invest?",
];

export default function CopilotChat({ onApplied }: { onApplied?: () => void }) {
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const newId = () => crypto.randomUUID();

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const conversation = conversationRef.current;
      conversation?.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, busy]);

  const requestReply = async (history: CopilotMessage[]) => {
    setError(null);
    setMessages(history);
    setBusy(true);
    try {
      const res = await api.chat(history.map((m) => ({ role: m.role, content: m.content })));
      setMessages([
        ...history,
        { id: newId(), role: "assistant", content: res.reply || "(no reply)", actions: res.actions },
      ]);
      if (res.ui_actions?.length) applyDashboardUiActions(res.ui_actions as DashboardUiAction[]);
      if (res.refresh) onApplied?.();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Audel couldn't respond. Please try again.");
      setMessages(history); // keep the user's message; drop the pending assistant turn
    } finally {
      setBusy(false);
    }
  };

  const send = (text: string) => {
    const content = text.trim();
    if (!content || busy) return;

    const history = editingMessageId
      ? branchConversation(messages, editingMessageId, content, newId())
      : [...messages, { id: newId(), role: "user" as const, content }];
    if (!history) return;

    setInput("");
    setEditingMessageId(null);
    void requestReply(history);
  };

  const beginEditing = (message: CopilotMessage) => {
    if (busy) return;
    setEditingMessageId(message.id);
    setInput(message.content);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const cancelEditing = () => {
    setEditingMessageId(null);
    setInput("");
  };

  const resend = (message: CopilotMessage) => {
    if (busy) return;
    const history = branchConversation(messages, message.id, undefined, newId());
    if (!history) return;
    cancelEditing();
    void requestReply(history);
  };

  return (
    <div className="flex flex-col bg-white rounded-xl border border-slate-200 lg:h-[calc(100vh-8rem)]">
      <div className="px-4 py-3 border-b border-slate-200 font-semibold">✨ Audel</div>

      <div ref={conversationRef} className="flex-1 overflow-y-auto p-3 space-y-3 min-h-[16rem]">
        {messages.length === 0 && (
          <div className="text-sm text-slate-500">
            <p className="mb-2">
              Ask Audel about your budgets, spending, portfolio, or where to invest. Audel coordinates a
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

        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
              m.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-800"
            }`}>
              <CopilotMarkdownText content={m.content} />
            </div>
            {m.actions && m.actions.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {m.actions.map((a, j) => (
                  <li key={j} className="text-xs text-emerald-600">✓ {a}</li>
                ))}
              </ul>
            )}
            {m.role === "user" && (
              <div className="mt-1 flex justify-end gap-3 text-xs text-slate-500">
                <button type="button" onClick={() => beginEditing(m)} disabled={busy}
                  className="hover:text-slate-900 disabled:opacity-40" aria-label="Edit and resend prompt">
                  ✎ Edit
                </button>
                <button type="button" onClick={() => resend(m)} disabled={busy}
                  className="hover:text-slate-900 disabled:opacity-40" aria-label="Resend prompt">
                  ↻ Resend
                </button>
              </div>
            )}
          </div>
        ))}

        {busy && <div className="text-sm text-slate-400">Thinking…</div>}
      </div>

      {error && (
        <div className="mx-3 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="p-3 border-t border-slate-200">
        {editingMessageId && (
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
            <span>✎ Editing prompt</span>
            <button type="button" onClick={cancelEditing} className="font-medium hover:text-slate-900">
              Cancel
            </button>
          </div>
        )}
        <div className="flex gap-2">
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Audel about your money…" disabled={busy}
            className="flex-1 border rounded-lg px-3 py-2 text-sm" />
          <button disabled={busy || !input.trim()}
            className="px-3 py-2 rounded-lg bg-slate-900 text-white text-sm disabled:opacity-50">
            {editingMessageId ? "Save & resend" : "Send"}
          </button>
        </div>
      </form>
    </div>
  );
}

function CopilotMarkdownText({ content }: { content: string }) {
  return (
    <div className="space-y-2 text-left">
      {parseCopilotContent(content).map((block, index) => (
        block.type === "text"
          ? <div key={index}><CopilotInlineMarkdownText content={block.content} /></div>
          : <CopilotTableCards key={index} headers={block.headers} rows={block.rows} />
      ))}
    </div>
  );
}

function CopilotInlineMarkdownText({ content }: { content: string }) {
  return parseInlineMarkdown(content).map((segment, index) => {
    if (segment.style === "bold") return <strong key={index}>{segment.text}</strong>;
    if (segment.style === "italic") return <em key={index}>{segment.text}</em>;
    if (segment.style === "boldItalic") {
      return <strong key={index}><em>{segment.text}</em></strong>;
    }
    return <span key={index}>{segment.text}</span>;
  });
}

function CopilotTableCards({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="space-y-2" aria-label="Comparison table">
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="rounded-xl border border-current/20 bg-black/5 p-2.5">
          <div className="font-semibold">
            <CopilotInlineMarkdownText content={row[0]} />
          </div>
          <dl className="mt-1.5 space-y-1">
            {headers.slice(1).map((header, columnIndex) => (
              <div key={header} className="flex items-start justify-between gap-4">
                <dt className="text-xs opacity-60">{header}</dt>
                <dd className="text-right text-xs font-medium">
                  <CopilotInlineMarkdownText content={row[columnIndex + 1]} />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
