export function formatCurrency(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

// "2026-07-15" -> "Jul 15". Parse the parts explicitly and render in UTC so the
// date never drifts a day in negative-offset timezones.
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// "2026-07-15" -> "7/15/2026" (American M/D/YYYY). Built in local time so it never
// drifts a day, and pinned to en-US regardless of the browser's locale.
export function formatDateFull(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US");
}

// A stored UTC timestamp (naive ISO from the backend) -> American M/D/YYYY in the
// viewer's LOCAL timezone (so a late-evening entry doesn't show tomorrow's date).
export function formatTimestampDate(iso: string): string {
  const s = /[Zz]$|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
  return new Date(s).toLocaleDateString("en-US");
}

export function prettifyCategory(s: string): string {
  return s
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
