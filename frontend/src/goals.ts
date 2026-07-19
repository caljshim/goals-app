import type { Goal } from "./types";

// Local day key ("YYYY-MM-DD") of a stored (UTC) timestamp.
function dayKey(iso: string): string {
  const s = /[Zz]$|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(s);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Collapse a value history into one point PER DAY (the day's last value), carrying the
// value forward across days with no entry — so the chart's x-axis is real days, not inputs.
export function dailySeries(history: { value: number; at: string }[]): { day: string; value: number }[] {
  if (history.length === 0) return [];
  const byDay = new Map<string, number>();
  for (const h of history) byDay.set(dayKey(h.at), h.value); // later entries overwrite -> last of the day
  const keys = [...byDay.keys()].sort();
  const out: { day: string; value: number }[] = [];
  const cur = new Date(`${keys[0]}T00:00:00`);
  const end = new Date(`${keys[keys.length - 1]}T00:00:00`);
  let last = byDay.get(keys[0]) as number;
  while (cur <= end) {
    const k = `${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, "0")}-${String(cur.getDate()).padStart(2, "0")}`;
    if (byDay.has(k)) last = byDay.get(k) as number;
    out.push({ day: k, value: last });
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

// Overall % for a group of goals (the "Auto" rule): sum toward the combined total when
// every member shares a unit and has a target (e.g. all lbs -> 850/1000), otherwise the
// average of each member's %. null when nothing is measurable.
export function groupAggregate(goals: Goal[]): number | null {
  const measurable = goals.filter((g) => g.target != null && g.target !== 0);
  if (measurable.length === 0) return null;
  const units = new Set(measurable.map((g) => g.unit));
  if (units.size === 1) {
    const cur = measurable.reduce((s, g) => s + g.current_value, 0);
    const tgt = measurable.reduce((s, g) => s + (g.target ?? 0), 0);
    return tgt ? Math.round((cur / tgt) * 1000) / 10 : null;
  }
  const pcts = measurable.map((g) => g.pct ?? 0);
  return Math.round((pcts.reduce((a, b) => a + b, 0) / pcts.length) * 10) / 10;
}

function mdFromKey(day: string): string {
  const [, m, d] = day.split("-");
  return `${Number(m)}/${Number(d)}`;
}

// Merge a category's goals into ONE dataset for a combined chart: one series per goal,
// aligned by day. If the goals share a unit, plots raw values; otherwise normalizes each
// to % of its target so different scales overlay meaningfully. Goals with no history are
// dropped. `data` rows are keyed by goal name; missing days are left absent (line gaps).
export function categorySeries(goals: Goal[]): {
  data: Record<string, number | string>[];
  keys: string[];
  percent: boolean;
} {
  const percent = new Set(goals.map((g) => g.unit)).size > 1;
  const perGoal = goals.map((g) => {
    const raw = dailySeries(g.history);
    const series = percent && g.target
      ? raw.map((p) => ({ day: p.day, value: Math.round((p.value / (g.target as number)) * 1000) / 10 }))
      : raw;
    return { name: g.name, byDay: new Map(series.map((p) => [p.day, p.value])) };
  });
  const allDays = [...new Set(perGoal.flatMap((p) => [...p.byDay.keys()]))].sort();
  const data = allDays.map((day) => {
    const row: Record<string, number | string> = { day: mdFromKey(day) };
    for (const p of perGoal) {
      const v = p.byDay.get(day);
      if (v != null) row[p.name] = v;
    }
    return row;
  });
  return { data, keys: perGoal.filter((p) => p.byDay.size > 0).map((p) => p.name), percent };
}

// Pace from a value trajectory: per-week rate of change, and weeks-to-target (null unless
// heading toward a target you haven't reached). null with fewer than two dated points.
export function goalPace(
  history: { value: number; at: string }[],
  target: number | null,
): { perWeek: number; etaWeeks: number | null } | null {
  if (history.length < 2) return null;
  const first = history[0];
  const last = history[history.length - 1];
  const days = (new Date(last.at).getTime() - new Date(first.at).getTime()) / 86_400_000;
  if (days <= 0) return null;
  const perWeek = ((last.value - first.value) / days) * 7;
  let etaWeeks: number | null = null;
  if (target != null && perWeek > 0 && last.value < target) {
    etaWeeks = (target - last.value) / perWeek;
  }
  return {
    perWeek: Math.round(perWeek * 10) / 10,
    etaWeeks: etaWeeks != null ? Math.round(etaWeeks * 10) / 10 : null,
  };
}
