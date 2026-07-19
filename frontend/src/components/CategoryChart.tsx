import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { categorySeries } from "../goals";
import type { Goal } from "../types";

const COLORS = ["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#f43f5e"];

/** One combined chart for a category: a line per goal, aligned by day. */
export default function CategoryChart({ goals }: { goals: Goal[] }) {
  const { data, keys, percent } = categorySeries(goals);
  if (data.length === 0 || keys.length === 0) {
    return <p className="text-xs text-slate-400">No history to chart yet — log some progress.</p>;
  }
  return (
    <ResponsiveContainer width="100%" height={210}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <XAxis dataKey="day" tick={{ fontSize: 9 }} minTickGap={24} />
        <YAxis width={44} tick={{ fontSize: 10 }} domain={["auto", "auto"]}
          tickFormatter={(v) => (percent ? `${v}%` : `${v}`)} />
        <Tooltip formatter={(v) => (percent ? `${v}%` : v)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {keys.map((k, i) => (
          <Line key={k} type="monotone" dataKey={k} stroke={COLORS[i % COLORS.length]}
            strokeWidth={2} dot={{ r: 2 }} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
