import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ScheduleItem } from "../types";

function dayKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function monthLabel(date: Date) {
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function dateLabel(value: string, includeWeekday = true) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    weekday: includeWeekday ? "long" : undefined,
    month: "short",
    day: "numeric",
  });
}

function monthGrid(month: Date): (Date | null)[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const out: (Date | null)[] = Array.from({ length: first.getDay() }, () => null);
  for (let day = 1; day <= last.getDate(); day += 1) out.push(new Date(month.getFullYear(), month.getMonth(), day));
  while (out.length % 7) out.push(null);
  return out;
}

function sourceColor(source: ScheduleItem["source"]) {
  if (source === "event") return "bg-blue-500";
  if (source === "reminder") return "bg-amber-500";
  if (source === "goal_deadline") return "bg-rose-500";
  return "bg-emerald-600";
}

function formatTime(value: string | null) {
  if (!value) return "";
  const [hour, minute] = value.split(":").map(Number);
  return new Date(2000, 0, 1, hour, minute).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function itemDescription(item: ScheduleItem) {
  if (item.missed) return "Missed";
  if (item.source === "event") return item.location ? `Event · ${item.location}` : "Event";
  if (item.source === "goal_deadline") return "Goal deadline";
  if (item.source === "routine") return `${item.period} routine`;
  if (item.repeat_until_completed) return `Reminds every ${item.nudge_interval_minutes ?? 60} min until done`;
  return "Reminder";
}

function AgendaItems({
  items,
  onChange,
  allowDelete = false,
}: {
  items: ScheduleItem[];
  onChange: () => void;
  allowDelete?: boolean;
}) {
  const today = dayKey(new Date());
  const toggle = async (item: ScheduleItem) => {
    if (item.source === "event" || item.source === "goal_deadline" || item.scheduled_for > today) return;
    if (item.source === "reminder") await api.setReminderCompleted(item.source_id, !item.completed);
    else await api.setGoalCheckin(item.source_id, item.scheduled_for, !item.completed, item.missed);
    onChange();
  };
  const remove = async (item: ScheduleItem) => {
    if (item.source === "event") await api.deleteEvent(item.source_id);
    else await api.deleteReminder(item.source_id);
    onChange();
  };

  if (items.length === 0) return <p className="text-sm text-slate-400">Nothing scheduled.</p>;
  return (
    <div className="grid gap-1">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-2 rounded-lg py-2">
          <button
            onClick={() => toggle(item)}
            disabled={item.source === "event" || item.source === "goal_deadline" || item.scheduled_for > today}
            aria-label={item.completed ? `Mark ${item.title} incomplete` : `Complete ${item.title}`}
            className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border text-xs ${
              item.completed ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300"
            }`}
          >
            {item.completed ? "✓" : ""}
          </button>
          <div className="min-w-0 flex-1">
            <p className={`text-sm font-medium ${item.completed ? "line-through text-slate-400" : ""}`}>{item.title}</p>
            <p className={`text-xs ${item.missed ? "text-red-600" : "text-slate-400"}`}>{itemDescription(item)}</p>
          </div>
          {item.reminder_time && (
            <span className="text-xs text-slate-400">
              {formatTime(item.reminder_time)}{item.end_time ? `–${formatTime(item.end_time)}` : ""}
            </span>
          )}
          {allowDelete && (item.source === "reminder" || item.source === "event") && (
            <button onClick={() => remove(item)} className="text-xs text-red-500">Delete</button>
          )}
        </div>
      ))}
    </div>
  );
}

/** Reusable calendar widget for the Schedule page and customizable dashboard. */
export default function ScheduleCalendar({ allowCreate = false }: { allowCreate?: boolean }) {
  const today = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [selected, setSelected] = useState(dayKey(today));
  const [showingDay, setShowingDay] = useState(false);
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const [adding, setAdding] = useState<"event" | "reminder" | null>(null);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(selected);
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [endTime, setEndTime] = useState("");
  const [location, setLocation] = useState("");
  const [persistent, setPersistent] = useState(false);
  const [nudgeMinutes, setNudgeMinutes] = useState(60);
  const [error, setError] = useState<string | null>(null);
  const days = useMemo(() => monthGrid(month), [month]);
  const rangeStart = dayKey(new Date(month.getFullYear(), month.getMonth(), 1));
  const rangeEnd = dayKey(new Date(month.getFullYear(), month.getMonth() + 1, 0));

  const load = useCallback(() => {
    api.getSchedule(rangeStart, rangeEnd).then(setItems).catch(() => setError("Could not load the schedule."));
  }, [rangeEnd, rangeStart]);
  useEffect(load, [load]);

  const selectedItems = items.filter((item) => item.scheduled_for === selected);
  const shiftMonth = (amount: number) => {
    const next = new Date(month.getFullYear(), month.getMonth() + amount, 1);
    setMonth(next);
  };
  const openDay = (value: string) => {
    setSelected(value);
    setDate(value);
    setAdding(null);
    setShowingDay(true);
  };
  const addReminder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    await api.createReminder({
      title: title.trim(),
      scheduled_for: date,
      reminder_time: time || null,
      notes: notes.trim() || null,
      repeat_until_completed: Boolean(time) && persistent,
      nudge_interval_minutes: Boolean(time) && persistent ? nudgeMinutes : null,
    });
    setTitle("");
    setTime("");
    setNotes("");
    setPersistent(false);
    setAdding(null);
    setSelected(date);
    load();
  };
  const addEvent = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    await api.createEvent({
      title: title.trim(),
      scheduled_for: date,
      start_time: time || null,
      end_time: time && endTime ? endTime : null,
      location: location.trim() || null,
      notes: notes.trim() || null,
    });
    setTitle("");
    setTime("");
    setEndTime("");
    setLocation("");
    setNotes("");
    setAdding(null);
    setSelected(date);
    load();
  };

  return (
    <>
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <button onClick={() => shiftMonth(-1)} aria-label="Previous month" className="p-1 text-slate-500">‹</button>
          <h3 className="font-semibold">{monthLabel(month)}</h3>
          <button onClick={() => shiftMonth(1)} aria-label="Next month" className="p-1 text-slate-500">›</button>
        </div>
        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
        <div className="grid grid-cols-7 gap-1 text-center">
          {["S", "M", "T", "W", "T", "F", "S"].map((day, index) => (
            <span key={`${day}-${index}`} className="pb-1 text-xs font-semibold text-slate-400">{day}</span>
          ))}
          {days.map((day, index) => day ? (
            <button
              key={dayKey(day)}
              onClick={() => openDay(dayKey(day))}
              className={`min-h-11 rounded-lg p-1 text-sm ${selected === dayKey(day) ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}
            >
              <span>{day.getDate()}</span>
              <span className="mt-1 flex justify-center gap-0.5">
                {[...new Set(items.filter((item) => item.scheduled_for === dayKey(day)).map((item) => item.source))]
                  .slice(0, 3).map((source) => <i key={source} className={`h-1 w-1 rounded-full ${sourceColor(source)}`} />)}
              </span>
            </button>
          ) : <span key={`blank-${index}`} />)}
        </div>
      </section>

      {showingDay && (
        <div className="fixed inset-0 z-50 grid place-items-end bg-slate-950/30 p-0 sm:place-items-center sm:p-6" onMouseDown={() => setShowingDay(false)}>
          <section className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-lg sm:rounded-2xl" onMouseDown={(event) => event.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Schedule</p>
                <h3 className="text-lg font-semibold">{dateLabel(selected)}</h3>
              </div>
              <div className="flex items-center gap-3">
                {allowCreate && (
                  <>
                    <button onClick={() => setAdding("event")} className="text-sm font-medium text-blue-700">+ Event</button>
                    <button onClick={() => setAdding("reminder")} className="text-sm font-medium text-emerald-700">+ Reminder</button>
                  </>
                )}
                <button onClick={() => setShowingDay(false)} aria-label="Close day" className="text-xl leading-none text-slate-400">×</button>
              </div>
            </div>
            <AgendaItems items={selectedItems} onChange={load} allowDelete={allowCreate} />
            {adding === "reminder" && (
              <form onSubmit={addReminder} className="mt-4 grid gap-3 rounded-xl bg-slate-50 p-3">
                <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Reminder" className="rounded border px-2 py-1.5 text-sm" />
                <div className="grid grid-cols-2 gap-2">
                  <input type="date" value={date} onChange={(event) => setDate(event.target.value)} className="rounded border px-2 py-1.5 text-sm" />
                  <input type="time" value={time} onChange={(event) => { setTime(event.target.value); if (!event.target.value) setPersistent(false); }} className="rounded border px-2 py-1.5 text-sm" />
                </div>
                <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Notes (optional)" className="rounded border px-2 py-1.5 text-sm" />
                {time && (
                  <>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={persistent} onChange={(event) => setPersistent(event.target.checked)} />
                      Keep nudging until I respond
                    </label>
                    {persistent && (
                      <label className="flex items-center justify-between gap-3 text-sm text-slate-600">
                        Remind me every
                        <select value={nudgeMinutes} onChange={(event) => setNudgeMinutes(Number(event.target.value))} className="rounded border bg-white px-2 py-1.5 text-sm">
                          <option value={30}>30 minutes</option>
                          <option value={60}>1 hour</option>
                          <option value={120}>2 hours</option>
                          <option value={240}>4 hours</option>
                        </select>
                      </label>
                    )}
                  </>
                )}
                <div className="flex justify-end gap-3">
                  <button type="button" onClick={() => setAdding(null)} className="text-sm text-slate-500">Cancel</button>
                  <button className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white">Add reminder</button>
                </div>
              </form>
            )}
            {adding === "event" && (
              <form onSubmit={addEvent} className="mt-4 grid gap-3 rounded-xl bg-slate-50 p-3">
                <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Event name" className="rounded border px-2 py-1.5 text-sm" />
                <input type="date" value={date} onChange={(event) => setDate(event.target.value)} className="rounded border px-2 py-1.5 text-sm" />
                <div className="grid grid-cols-2 gap-2">
                  <label className="grid gap-1 text-xs text-slate-500">Starts
                    <input type="time" value={time} onChange={(event) => { setTime(event.target.value); if (!event.target.value) setEndTime(""); }} className="rounded border px-2 py-1.5 text-sm text-slate-900" />
                  </label>
                  <label className="grid gap-1 text-xs text-slate-500">Ends
                    <input type="time" value={endTime} min={time || undefined} disabled={!time} onChange={(event) => setEndTime(event.target.value)} className="rounded border px-2 py-1.5 text-sm text-slate-900 disabled:bg-slate-100" />
                  </label>
                </div>
                <input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Location (optional)" className="rounded border px-2 py-1.5 text-sm" />
                <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Notes (optional)" className="rounded border px-2 py-1.5 text-sm" />
                <div className="flex justify-end gap-3">
                  <button type="button" onClick={() => setAdding(null)} className="text-sm text-slate-500">Cancel</button>
                  <button className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white">Add event</button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}
    </>
  );
}

/** Reusable agenda widget for today's Schedule view and dashboard. */
export function ScheduleToday() {
  const today = dayKey(new Date());
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const load = useCallback(() => { api.getSchedule(today, today).then(setItems).catch(() => {}); }, [today]);
  useEffect(load, [load]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 font-semibold">Today's schedule</h3>
      <AgendaItems items={items} onChange={load} />
    </section>
  );
}
