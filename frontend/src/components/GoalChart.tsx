import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCurrency } from "../format";
import { dailySeries } from "../goals";

function fmt(v: number, unit: string): string {
  if (unit === "$") return formatCurrency(v);
  if (unit === "days") return `${v}d`;
  return v.toLocaleString();
}

// "2026-07-15" -> "7/15"
function mdLabel(day: string): string {
  const [, m, d] = day.split("-");
  return `${Number(m)}/${Number(d)}`;
}

/** Per-day trajectory line for a goal, with dashed markers at each cleared milestone. */
export default function GoalChart({
  history,
  milestones,
  unit,
}: {
  history: { value: number; at: string }[];
  milestones: { value: number; at: string }[];
  unit: string;
}) {
  // Always one point per calendar day. A single day shows as one dot; it becomes a line
  // as you log on more days.
  const data = dailySeries(history).map((s) => ({ x: mdLabel(s.day), value: s.value }));
  if (data.length === 0) return null;
  return (
    <ResponsiveContainer width="100%" height={150}>
      <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -8 }}>
        <XAxis dataKey="x" tick={{ fontSize: 9 }} minTickGap={24} />
        <YAxis domain={["auto", "auto"]} width={44} tick={{ fontSize: 10 }}
          tickFormatter={(v) => fmt(Number(v), unit)} />
        <Tooltip formatter={(v) => [fmt(Number(v), unit), ""]} labelFormatter={(l) => l} />
        {milestones.map((m, i) => (
          <ReferenceLine key={i} y={m.value} stroke="#f59e0b" strokeDasharray="3 3" />
        ))}
        <Line type="monotone" dataKey="value" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
