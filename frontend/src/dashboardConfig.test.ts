import { describe, expect, it } from "vitest";
import { normalizeDashboardWidgets } from "./dashboardConfig";

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
