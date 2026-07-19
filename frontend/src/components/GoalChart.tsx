import { useEffect, useState } from "react";
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

type ChartRange = "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL";
const CHART_RANGES: { label: ChartRange; days: number | null }[] = [
  { label: "1W", days: 7 }, { label: "1M", days: 30 },
  { label: "3M", days: 90 }, { label: "6M", days: 180 },
  { label: "1Y", days: 365 }, { label: "ALL", days: null },
];

function cutoffDay(days: number): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function GoalChartRangeSelector({ value, onChange }: {
  value: ChartRange;
  onChange: (range: ChartRange) => void;
}) {
  return (
    <div className="mb-2 flex items-center justify-between" aria-label="Chart time range">
      {CHART_RANGES.map(({ label }) => (
        <button key={label} type="button" onClick={() => onChange(label)}
          className={`border-b-2 px-1 py-1 text-[11px] font-semibold ${value === label ? "border-sky-500 text-sky-700" : "border-transparent text-slate-400 hover:text-slate-600"}`}>
          {label === "ALL" ? "All" : label}
        </button>
      ))}
    </div>
  );
}

/** Per-day trajectory line for a goal, with dashed markers at each cleared milestone. */
export default function GoalChart({
  history,
  milestones,
  unit,
  target,
  storageKey,
}: {
  history: { value: number; at: string }[];
  milestones: { value: number; at: string }[];
  unit: string;
  target?: number | null;
  storageKey?: string;
}) {
  const localKey = `money.ui.goalChart.${storageKey ?? "default"}.range`;
  const [range, setRange] = useState<ChartRange>(() => {
    const saved = localStorage.getItem(localKey) as ChartRange | null;
    return CHART_RANGES.some((item) => item.label === saved) ? saved as ChartRange : "1W";
  });
  useEffect(() => { localStorage.setItem(localKey, range); }, [localKey, range]);
  // Always one point per calendar day. A single day shows as one dot; it becomes a line
  // as you log on more days.
  const selectedDays = CHART_RANGES.find((item) => item.label === range)?.days ?? null;
  const allData = dailySeries(history);
  const visible = selectedDays == null
    ? allData
    : allData.filter((point) => point.day >= cutoffDay(selectedDays));
  const data = visible.map((s) => ({ x: mdLabel(s.day), value: s.value }));
  if (allData.length === 0) return null;
  return (
    <div>
      <GoalChartRangeSelector value={range} onChange={setRange} />
      {data.length === 0 ? (
        <p className="py-10 text-center text-xs text-slate-400">No points in this range yet.</p>
      ) : (
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -8 }}>
            <XAxis dataKey="x" tick={{ fontSize: 9 }} minTickGap={24} />
            <YAxis domain={["auto", "auto"]} width={44} tick={{ fontSize: 10 }}
              tickFormatter={(v) => fmt(Number(v), unit)} />
            <Tooltip formatter={(v) => [fmt(Number(v), unit), ""]} labelFormatter={(l) => l} />
            {target != null && <ReferenceLine y={target} stroke="#94a3b8" strokeDasharray="5 4" />}
            {milestones.map((m, i) => (
              <ReferenceLine key={i} y={m.value} stroke="#f59e0b" strokeDasharray="3 3" />
            ))}
            <Line type="monotone" dataKey="value" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
