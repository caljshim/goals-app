import { describe, expect, it } from "vitest";
import { normalizeDashboardWidgets, reorderWidgets } from "./dashboardConfig";

describe("reorderWidgets", () => {
  it("moves a card downward to an insertion gap in original coordinates", () => {
    // Move "a" (index 0) into the gap before "c" (insertion index 2).
    expect(reorderWidgets(["a", "b", "c", "d"], 0, 2)).toEqual(["b", "a", "c", "d"]);
  });

  it("moves a card upward to an earlier gap", () => {
    // Move "d" (index 3) into the gap before "b" (insertion index 1).
    expect(reorderWidgets(["a", "b", "c", "d"], 3, 1)).toEqual(["a", "d", "b", "c"]);
  });

  it("moves a card to the very end", () => {
    expect(reorderWidgets(["a", "b", "c"], 0, 3)).toEqual(["b", "c", "a"]);
  });

  it("is a no-op when dropped in its own gap", () => {
    expect(reorderWidgets(["a", "b", "c"], 1, 1)).toEqual(["a", "b", "c"]);
    expect(reorderWidgets(["a", "b", "c"], 1, 2)).toEqual(["a", "b", "c"]);
  });

  it("returns the list unchanged for an out-of-range source", () => {
    expect(reorderWidgets(["a", "b"], 5, 0)).toEqual(["a", "b"]);
  });
});

describe("normalizeDashboardWidgets", () => {
  it("drops retired checklist widgets and migrates recurring sections to Routines", () => {
    expect(normalizeDashboardWidgets([
      "goal-todo-day",
      "goal-todo-week",
      "goal-section:daily",
      "goal-section:weekly",
    ])).toEqual([
      "routine-section:daily",
      "routine-section:weekly",
    ]);
  });

  it("keeps one-time goal widgets and removes duplicates or invalid IDs", () => {
    expect(normalizeDashboardWidgets([
      "goal-section:once",
      "goal-section:once",
      "routine-section:monthly",
      "not-a-widget",
      null,
    ])).toEqual([
      "goal-section:once",
      "routine-section:monthly",
    ]);
  });

  it("migrates saved streak sections from Routines to Goals", () => {
    expect(normalizeDashboardWidgets([
      "routine-section:ongoing",
      "goal-section:ongoing",
    ])).toEqual(["goal-section:ongoing"]);
  });

  it("keeps transaction review widgets", () => {
    expect(normalizeDashboardWidgets([
      "unbudgeted-transactions",
      "p2p-review",
    ])).toEqual([
      "unbudgeted-transactions",
      "p2p-review",
    ]);
  });
});
