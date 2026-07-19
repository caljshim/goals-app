import { prettifyCategory } from "./format";
import type { Transaction } from "./types";

// Everything a search query can match a transaction on, lower-cased.
function haystack(t: Transaction): string {
  return [
    t.merchant_name ?? "",
    t.name,
    t.effective_category,
    prettifyCategory(t.effective_category),
    t.date,
  ].join(" ").toLowerCase();
}

// Client-side transaction search: case-insensitive substring across merchant,
// description, category, and date. Every whitespace-separated term must match (AND).
export function filterTransactions(rows: Transaction[], query: string): Transaction[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return rows;
  return rows.filter((t) => {
    const h = haystack(t);
    return terms.every((term) => h.includes(term));
  });
}
