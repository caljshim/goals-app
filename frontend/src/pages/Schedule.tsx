import { useState } from "react";
import ScheduleCalendar, { ScheduleToday } from "../components/ScheduleCalendar";
import Goals from "./Goals";

export default function Schedule() {
  const [section, setSection] = useState<"routines" | "calendar">("routines");

  return (
    <div className="grid gap-5">
      <div>
        <h2 className="text-xl font-semibold">Schedule</h2>
        <p className="text-sm text-slate-500">Routines, reminders, and goal deadlines in one place.</p>
      </div>
      <nav className="grid grid-cols-2 rounded-xl bg-slate-100 p-1" aria-label="Schedule views">
        {(["routines", "calendar"] as const).map((value) => (
          <button
            key={value}
            onClick={() => setSection(value)}
            className={`rounded-lg px-3 py-2 text-sm font-medium capitalize transition ${section === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
          >
            {value}
          </button>
        ))}
      </nav>
      {section === "routines" && (
        <>
          <ScheduleToday />
          <Goals mode="routines" />
        </>
      )}
      {section === "calendar" && <ScheduleCalendar allowCreate />}
    </div>
  );
}
