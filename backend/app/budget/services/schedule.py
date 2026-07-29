from datetime import date, datetime, timedelta
import re

from sqlmodel import Session, select

from app.budget.models import CalendarEvent, Goal, GoalCheckin, Reminder
from app.budget.services import goals as goals_svc


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MIN_NUDGE_MINUTES = 30
MAX_NUDGE_MINUTES = 24 * 60


def _clean_title(value: str | None) -> str:
    title = (value or "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > 120:
        raise ValueError("title must be 120 characters or fewer")
    return title


def _clean_time(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    pieces = raw.split(":")
    if len(pieces) == 2 and all(piece.isdigit() for piece in pieces):
        raw = f"{int(pieces[0]):02d}:{int(pieces[1]):02d}"
    if not _TIME_RE.fullmatch(raw):
        raise ValueError("reminder_time must be HH:MM")
    return raw


def _clean_notes(value: str | None) -> str | None:
    if value is None:
        return None
    notes = value.strip()
    if len(notes) > 1000:
        raise ValueError("notes must be 1000 characters or fewer")
    return notes or None


def reminder_to_read(reminder: Reminder) -> dict:
    return {
        "id": reminder.id,
        "title": reminder.title,
        "scheduled_for": reminder.scheduled_for,
        "reminder_time": reminder.reminder_time,
        "notes": reminder.notes,
        "completed": reminder.completed_at is not None,
        "repeat_until_completed": reminder.repeat_until_completed,
        "nudge_interval_minutes": reminder.nudge_interval_minutes,
        "created_at": reminder.created_at,
    }


def _nudge_policy(data: dict, current: Reminder | None = None) -> tuple[bool, int | None]:
    persistent = bool(data.get(
        "repeat_until_completed",
        current.repeat_until_completed if current is not None else False,
    ))
    raw_interval = data.get(
        "nudge_interval_minutes",
        current.nudge_interval_minutes if current is not None else None,
    )
    interval = int(raw_interval) if raw_interval is not None else (60 if persistent else None)
    if persistent and not data.get("reminder_time", current.reminder_time if current else None):
        raise ValueError("persistent reminders require a reminder_time")
    if persistent and not MIN_NUDGE_MINUTES <= interval <= MAX_NUDGE_MINUTES:
        raise ValueError(
            f"nudge_interval_minutes must be between {MIN_NUDGE_MINUTES} and {MAX_NUDGE_MINUTES}"
        )
    return persistent, interval if persistent else None


def create_reminder(session: Session, data: dict) -> dict:
    reminder_time = _clean_time(data.get("reminder_time"))
    policy_data = {**data, "reminder_time": reminder_time}
    persistent, interval = _nudge_policy(policy_data)
    reminder = Reminder(
        title=_clean_title(data.get("title")),
        scheduled_for=data["scheduled_for"],
        reminder_time=reminder_time,
        notes=_clean_notes(data.get("notes")),
        repeat_until_completed=persistent,
        nudge_interval_minutes=interval,
    )
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder_to_read(reminder)


def list_reminders(session: Session, include_completed: bool = False) -> list[dict]:
    statement = select(Reminder).order_by(Reminder.scheduled_for, Reminder.reminder_time, Reminder.id)
    if not include_completed:
        statement = statement.where(Reminder.completed_at.is_(None))
    return [reminder_to_read(reminder) for reminder in session.exec(statement).all()]


def update_reminder(session: Session, reminder_id: int, data: dict) -> dict | None:
    reminder = session.get(Reminder, reminder_id)
    if reminder is None:
        return None
    if "title" in data:
        reminder.title = _clean_title(data["title"])
    if "scheduled_for" in data:
        if data["scheduled_for"] is None:
            raise ValueError("scheduled_for cannot be cleared")
        reminder.scheduled_for = data["scheduled_for"]
    if "reminder_time" in data:
        reminder.reminder_time = _clean_time(data["reminder_time"])
    if "notes" in data:
        reminder.notes = _clean_notes(data["notes"])
    if "repeat_until_completed" in data or "nudge_interval_minutes" in data or "reminder_time" in data:
        persistent, interval = _nudge_policy(data, reminder)
        reminder.repeat_until_completed = persistent
        reminder.nudge_interval_minutes = interval
    if "completed" in data:
        reminder.completed_at = datetime.utcnow() if data["completed"] else None
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder_to_read(reminder)


def delete_reminder(session: Session, reminder_id: int) -> bool:
    reminder = session.get(Reminder, reminder_id)
    if reminder is None:
        return False
    session.delete(reminder)
    session.commit()
    return True


def event_to_read(event: CalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "scheduled_for": event.scheduled_for,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "location": event.location,
        "notes": event.notes,
        "created_at": event.created_at,
    }


def _event_times(start_time: str | None, end_time: str | None) -> tuple[str | None, str | None]:
    start = _clean_time(start_time)
    end = _clean_time(end_time)
    if end is not None and start is None:
        raise ValueError("end_time requires a start_time")
    if start is not None and end is not None and end <= start:
        raise ValueError("end_time must be after start_time")
    return start, end


def _event_from_data(data: dict) -> CalendarEvent:
    start, end = _event_times(data.get("start_time"), data.get("end_time"))
    return CalendarEvent(
        title=_clean_title(data.get("title")),
        scheduled_for=data["scheduled_for"],
        start_time=start,
        end_time=end,
        location=_clean_notes(data.get("location")),
        notes=_clean_notes(data.get("notes")),
    )


def create_event(session: Session, data: dict) -> dict:
    event = _event_from_data(data)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event_to_read(event)


def create_events(session: Session, items: list[dict]) -> dict:
    if not items:
        raise ValueError("events must not be empty")
    if len(items) > 50:
        raise ValueError("at most 50 events can be created at once")

    candidates = [_event_from_data(item) for item in items]
    existing = {
        (
            event.title.casefold(),
            event.scheduled_for,
            event.start_time,
            event.end_time,
        )
        for event in session.exec(select(CalendarEvent)).all()
    }
    created: list[CalendarEvent] = []
    skipped: list[str] = []
    seen = set(existing)
    for event in candidates:
        key = (
            event.title.casefold(),
            event.scheduled_for,
            event.start_time,
            event.end_time,
        )
        if key in seen:
            skipped.append(event.title)
            continue
        seen.add(key)
        session.add(event)
        created.append(event)
    session.commit()
    for event in created:
        session.refresh(event)
    return {
        "created": [event_to_read(event) for event in created],
        "skipped_duplicates": skipped,
    }


def list_events(
    session: Session, start: date | None = None, end: date | None = None
) -> list[dict]:
    statement = select(CalendarEvent).order_by(
        CalendarEvent.scheduled_for, CalendarEvent.start_time, CalendarEvent.id
    )
    if start is not None:
        statement = statement.where(CalendarEvent.scheduled_for >= start)
    if end is not None:
        statement = statement.where(CalendarEvent.scheduled_for <= end)
    return [event_to_read(event) for event in session.exec(statement).all()]


def update_event(session: Session, event_id: int, data: dict) -> dict | None:
    event = session.get(CalendarEvent, event_id)
    if event is None:
        return None
    if "title" in data:
        event.title = _clean_title(data["title"])
    if "scheduled_for" in data:
        if data["scheduled_for"] is None:
            raise ValueError("scheduled_for cannot be cleared")
        event.scheduled_for = data["scheduled_for"]
    if "start_time" in data or "end_time" in data:
        start, end = _event_times(
            data.get("start_time", event.start_time),
            data.get("end_time", event.end_time),
        )
        event.start_time = start
        event.end_time = end
    if "location" in data:
        event.location = _clean_notes(data["location"])
    if "notes" in data:
        event.notes = _clean_notes(data["notes"])
    session.add(event)
    session.commit()
    session.refresh(event)
    return event_to_read(event)


def delete_event(session: Session, event_id: int) -> bool:
    event = session.get(CalendarEvent, event_id)
    if event is None:
        return False
    session.delete(event)
    session.commit()
    return True


def list_schedule(session: Session, start: date, end: date) -> list[dict]:
    if end < start:
        raise ValueError("end must be on or after start")
    if (end - start).days > 366:
        raise ValueError("schedule range cannot exceed 366 days")

    today = date.today()
    items: list[dict] = []
    events = session.exec(
        select(CalendarEvent)
        .where(CalendarEvent.scheduled_for >= start, CalendarEvent.scheduled_for <= end)
        .order_by(CalendarEvent.scheduled_for, CalendarEvent.start_time, CalendarEvent.id)
    ).all()
    for event in events:
        items.append({
            "id": f"event:{event.id}", "source": "event", "source_id": event.id,
            "title": event.title, "scheduled_for": event.scheduled_for,
            "reminder_time": event.start_time, "end_time": event.end_time,
            "completed": False, "missed": False, "notes": event.notes,
            "location": event.location, "period": None,
            "repeat_until_completed": False, "nudge_interval_minutes": None,
        })

    reminders = session.exec(
        select(Reminder)
        .where(Reminder.scheduled_for >= start, Reminder.scheduled_for <= end)
        .order_by(Reminder.scheduled_for, Reminder.reminder_time, Reminder.id)
    ).all()
    for reminder in reminders:
        completed = reminder.completed_at is not None
        items.append({
            "id": f"reminder:{reminder.id}", "source": "reminder", "source_id": reminder.id,
            "title": reminder.title, "scheduled_for": reminder.scheduled_for,
            "reminder_time": reminder.reminder_time, "completed": completed,
            "missed": reminder.scheduled_for < today and not completed,
            "notes": reminder.notes, "period": None,
            "repeat_until_completed": reminder.repeat_until_completed,
            "nudge_interval_minutes": reminder.nudge_interval_minutes,
            "end_time": None, "location": None,
        })

    # Calendar history is immutable user history, not merely a projection of the
    # currently active goal list. Ended goals and routines therefore remain
    # visible through the day they were archived.
    goals = session.exec(select(Goal).order_by(Goal.name)).all()
    checkins = session.exec(select(GoalCheckin)).all()
    completed_occurrences = {(item.goal_id, item.scheduled_for) for item in checkins}
    goal_context = None

    span = (end - start).days
    for goal in goals:
        if goal.period in {"daily", "weekly", "monthly", "interval"}:
            for offset in range(span + 1):
                scheduled = start + timedelta(days=offset)
                if not goals_svc.routine_occurs_on(
                    goal,
                    scheduled,
                    today=today,
                    include_archived_history=True,
                ):
                    continue
                completed = (goal.id, scheduled) in completed_occurrences
                items.append({
                    "id": f"routine:{goal.id}:{scheduled.isoformat()}", "source": "routine",
                    "source_id": goal.id, "title": goal.name, "scheduled_for": scheduled,
                    "reminder_time": goal.reminder_time, "completed": completed,
                    "missed": scheduled < today and not completed, "notes": None,
                    "period": goal.period,
                    "repeat_until_completed": goal.repeat_until_completed,
                    "nudge_interval_minutes": goal.nudge_interval_minutes,
                    "end_time": None, "location": None,
                })

        archive_date = goal.archived_at.date() if goal.archived_at is not None else None
        if (
            goal.deadline is not None
            and start <= goal.deadline <= end
            and (archive_date is None or goal.deadline <= archive_date)
        ):
            if goal_context is None:
                goal_context = goals_svc.build_context(session)
            progress = goals_svc.goal_progress(goal, goal_context)
            completed = progress["status"] in {"reached", "milestone"}
            items.append({
                "id": f"goal_deadline:{goal.id}", "source": "goal_deadline",
                "source_id": goal.id, "title": goal.name, "scheduled_for": goal.deadline,
                "reminder_time": None, "completed": completed,
                "missed": goal.deadline < today and not completed,
                "notes": "Goal deadline", "period": None,
                "repeat_until_completed": False, "nudge_interval_minutes": None,
                "end_time": None, "location": None,
            })

    return sorted(items, key=lambda item: (
        item["scheduled_for"], item["reminder_time"] or "99:99", item["title"].casefold(), item["id"]
    ))
