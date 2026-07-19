import { describe, expect, it } from "vitest";
import { categorySeries, dailySeries, goalPace, groupAggregate } from "./goals";
import type { Goal } from "./types";

function g(p: Partial<Goal>): Goal {
  return {
    id: 1, name: "x", kind: "numeric", period: "once", direction: "reach", step: 1,
    target: null, account_id: null, category: null, current: null, since: null, deadline: null,
    group: null, current_value: 0, pct: null, status: "active", unit: "", linked_label: null,
    days: null, best_days: null, history: [], milestones: [], ...p,
  };
}

describe("groupAggregate", () => {
  it("sums toward the total when units match (1000 CLUB)", () => {
    const goals = [
      g({ unit: "", current_value: 200, target: 225, pct: 88.9 }),
      g({ unit: "", current_value: 300, target: 350, pct: 85.7 }),
      g({ unit: "", current_value: 350, target: 425, pct: 82.4 }),
    ];
    expect(groupAggregate(goals)).toBe(85); // 850 / 1000
  });
  it("averages the %s when units are mixed", () => {
    const goals = [
      g({ unit: "$", current_value: 2500, target: 5000, pct: 50 }),
      g({ unit: "days", current_value: 30, target: 90, pct: 33.3 }),
    ];
    expect(groupAggregate(goals)).toBe(41.7); // (50 + 33.3) / 2
  });
  it("returns null when nothing is measurable", () => {
    expect(groupAggregate([g({ target: null })])).toBeNull();
  });
});

describe("categorySeries", () => {
  const at = "2026-07-19T16:00:00";
  it("merges same-unit goals into one dataset with raw values", () => {
    const bench = g({ name: "Bench", unit: "", target: 225, history: [{ value: 155, at }] });
    const squat = g({ name: "Squat", unit: "", target: 315, history: [{ value: 185, at }] });
    const { data, keys, percent } = categorySeries([bench, squat]);
    expect(percent).toBe(false);
    expect(keys).toEqual(["Bench", "Squat"]);
    expect(data[0]).toMatchObject({ Bench: 155, Squat: 185 });
  });
  it("normalizes to % of target when units differ", () => {
    const fund = g({ name: "Fund", unit: "$", target: 1000, history: [{ value: 500, at }] });
    const reps = g({ name: "Reps", unit: "", target: 50, history: [{ value: 25, at }] });
    const { data, percent } = categorySeries([fund, reps]);
    expect(percent).toBe(true);
    expect(data[0]).toMatchObject({ Fund: 50, Reps: 50 }); // both 50% of target
  });
  it("drops goals with no history", () => {
    const a = g({ name: "A", unit: "", target: 10, history: [{ value: 5, at }] });
    const b = g({ name: "B", unit: "", target: 10, history: [] });
    expect(categorySeries([a, b]).keys).toEqual(["A"]);
  });
});

describe("dailySeries", () => {
  it("collapses multiple same-day inputs to the day's last value and carries gaps forward", () => {
    // 16:00 and 18:00 UTC fall on the same local day in every timezone; 07-03 is a gap day.
    const hist = [
      { value: 185, at: "2026-07-01T16:00:00" },
      { value: 195, at: "2026-07-01T18:00:00" },
      { value: 205, at: "2026-07-03T17:00:00" },
    ];
    const s = dailySeries(hist);
    expect(s.map((p) => p.value)).toEqual([195, 195, 205]); // day1 last, day2 carried, day3
    expect(s.length).toBe(3);
  });
  it("returns [] for empty history", () => {
    expect(dailySeries([])).toEqual([]);
  });
});

describe("goalPace", () => {
  it("computes per-week rate and ETA to target", () => {
    const hist = [
      { value: 185, at: "2026-07-01T00:00:00" },
      { value: 205, at: "2026-07-15T00:00:00" },
    ];
    const pace = goalPace(hist, 225)!;
    expect(pace.perWeek).toBe(10);   // +20 over 14 days -> 10/wk
    expect(pace.etaWeeks).toBe(2);   // (225-205)/10
  });
  it("returns null with fewer than two points", () => {
    expect(goalPace([{ value: 1, at: "2026-07-01" }], 10)).toBeNull();
  });
});
