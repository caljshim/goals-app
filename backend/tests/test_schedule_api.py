from datetime import date, datetime, timedelta

from app.budget.models import Goal


def test_one_time_reminder_lifecycle_and_schedule_projection(client):
    scheduled = date.today() + timedelta(days=2)
    created = client.post("/api/reminders", json={
        "title": "Call Mom", "scheduled_for": scheduled.isoformat(),
        "reminder_time": "9:05", "notes": "Ask about the trip",
    })
    assert created.status_code == 201
    reminder = created.json()
    assert reminder["reminder_time"] == "09:05"
    assert reminder["completed"] is False

    calendar = client.get("/api/schedule", params={
        "start": scheduled.isoformat(), "end": scheduled.isoformat(),
    })
    assert calendar.status_code == 200
    assert calendar.json()[0]["source"] == "reminder"
    assert calendar.json()[0]["title"] == "Call Mom"

    completed = client.patch(f"/api/reminders/{reminder['id']}", json={"completed": True})
    assert completed.status_code == 200 and completed.json()["completed"] is True
    assert client.delete(f"/api/reminders/{reminder['id']}").status_code == 204
    assert client.get("/api/schedule", params={
        "start": scheduled.isoformat(), "end": scheduled.isoformat(),
    }).json() == []


def test_schedule_merges_routines_and_goal_deadlines(client, session):
    today = date.today()
    weekday = today.strftime("%A").lower()
    routine = client.post("/api/goals", json={
        "name": "Church", "kind": "numeric", "target": 1,
        "period": "weekly", "weekly_days": [weekday], "reminder_time": "09:00",
        "repeat_until_completed": True, "nudge_interval_minutes": 120,
    }).json()
    goal = client.post("/api/goals", json={
        "name": "Finish portfolio", "kind": "numeric", "target": 10,
        "current": 2, "deadline": today.isoformat(),
    }).json()

    response = client.get("/api/schedule", params={
        "start": today.isoformat(), "end": today.isoformat(),
    })
    assert response.status_code == 200
    by_source = {item["source"]: item for item in response.json()}
    assert by_source["routine"]["source_id"] == routine["id"]
    assert by_source["routine"]["reminder_time"] == "09:00"
    assert by_source["routine"]["repeat_until_completed"] is True
    assert by_source["routine"]["nudge_interval_minutes"] == 120
    assert by_source["goal_deadline"]["source_id"] == goal["id"]
    assert by_source["goal_deadline"]["completed"] is False


def test_schedule_fills_arbitrary_calendar_range_for_daily_routine(client, session):
    made = client.post("/api/goals", json={
        "name": "Stretch", "kind": "numeric", "target": 1, "period": "daily",
    }).json()
    goal = session.get(Goal, made["id"])
    start = date.today() - timedelta(days=10)
    goal.created_at = datetime.combine(start, datetime.min.time())
    session.add(goal); session.commit()

    end = start + timedelta(days=3)
    items = client.get("/api/schedule", params={
        "start": start.isoformat(), "end": end.isoformat(),
    }).json()
    assert [item["scheduled_for"] for item in items] == [
        (start + timedelta(days=offset)).isoformat() for offset in range(4)
    ]


def test_schedule_keeps_ended_daily_routine_history(client, session):
    today = date.today()
    start = today - timedelta(days=5)
    ended = today - timedelta(days=2)
    made = client.post("/api/goals", json={
        "name": "Morning stretch", "kind": "numeric", "target": 1, "period": "daily",
    }).json()
    goal = session.get(Goal, made["id"])
    goal.created_at = datetime.combine(start, datetime.min.time())
    goal.archived_at = datetime.combine(ended, datetime.max.time())
    session.add(goal); session.commit()

    items = client.get("/api/schedule", params={
        "start": start.isoformat(), "end": today.isoformat(),
    }).json()
    routine_dates = [
        item["scheduled_for"] for item in items
        if item["source"] == "routine" and item["source_id"] == goal.id
    ]
    assert routine_dates == [
        (start + timedelta(days=offset)).isoformat() for offset in range(4)
    ]


def test_schedule_keeps_deadline_for_ended_unfinished_goal(client, session):
    deadline = date.today() - timedelta(days=3)
    made = client.post("/api/goals", json={
        "name": "Finish tax folder", "kind": "numeric", "target": 10,
        "current": 2, "deadline": deadline.isoformat(),
    }).json()
    assert client.delete(f"/api/goals/{made['id']}").status_code == 204

    items = client.get("/api/schedule", params={
        "start": deadline.isoformat(), "end": deadline.isoformat(),
    }).json()
    deadline_item = next(
        item for item in items
        if item["source"] == "goal_deadline" and item["source_id"] == made["id"]
    )
    assert deadline_item["completed"] is False
    assert deadline_item["missed"] is True


def test_schedule_rejects_unbounded_ranges_and_invalid_reminder_time(client):
    today = date.today()
    too_far = today + timedelta(days=367)
    assert client.get("/api/schedule", params={
        "start": today.isoformat(), "end": too_far.isoformat(),
    }).status_code == 400
    invalid = client.post("/api/reminders", json={
        "title": "Nope", "scheduled_for": today.isoformat(), "reminder_time": "25:00",
    })
    assert invalid.status_code == 400


def test_persistent_reminder_defaults_to_hourly_and_survives_schedule_projection(client):
    today = date.today()
    created = client.post("/api/reminders", json={
        "title": "Go to the grocery store", "scheduled_for": today.isoformat(),
        "reminder_time": "10:00", "repeat_until_completed": True,
    })
    assert created.status_code == 201
    assert created.json()["repeat_until_completed"] is True
    assert created.json()["nudge_interval_minutes"] == 60
    projected = client.get("/api/schedule", params={
        "start": today.isoformat(), "end": today.isoformat(),
    }).json()[0]
    assert projected["repeat_until_completed"] is True
    assert projected["nudge_interval_minutes"] == 60


def test_persistent_reminder_requires_time_and_rate_limits_nudges(client):
    today = date.today().isoformat()
    missing_time = client.post("/api/reminders", json={
        "title": "Groceries", "scheduled_for": today, "repeat_until_completed": True,
    })
    assert missing_time.status_code == 400
    too_frequent = client.post("/api/reminders", json={
        "title": "Groceries", "scheduled_for": today, "reminder_time": "10:00",
        "repeat_until_completed": True, "nudge_interval_minutes": 5,
    })
    assert too_frequent.status_code == 400


def test_calendar_event_lifecycle_and_schedule_projection(client):
    scheduled = date.today() + timedelta(days=3)
    created = client.post("/api/events", json={
        "title": "Dinner with Maya",
        "scheduled_for": scheduled.isoformat(),
        "start_time": "7:00",
        "end_time": "20:30",
        "location": "Little Star",
        "notes": "Patio table",
    })
    assert created.status_code == 201
    event = created.json()
    assert event["start_time"] == "07:00"
    assert event["end_time"] == "20:30"

    projected = client.get("/api/schedule", params={
        "start": scheduled.isoformat(), "end": scheduled.isoformat(),
    }).json()
    assert projected == [{
        "id": f"event:{event['id']}",
        "source": "event",
        "source_id": event["id"],
        "title": "Dinner with Maya",
        "scheduled_for": scheduled.isoformat(),
        "reminder_time": "07:00",
        "completed": False,
        "missed": False,
        "notes": "Patio table",
        "period": None,
        "repeat_until_completed": False,
        "nudge_interval_minutes": None,
        "end_time": "20:30",
        "location": "Little Star",
    }]

    updated = client.patch(f"/api/events/{event['id']}", json={"location": "Home"})
    assert updated.status_code == 200
    assert updated.json()["location"] == "Home"
    assert client.delete(f"/api/events/{event['id']}").status_code == 204


def test_calendar_event_validates_time_range(client):
    today = date.today().isoformat()
    missing_start = client.post("/api/events", json={
        "title": "Bad event", "scheduled_for": today, "end_time": "11:00",
    })
    assert missing_start.status_code == 400
    backwards = client.post("/api/events", json={
        "title": "Bad event", "scheduled_for": today,
        "start_time": "11:00", "end_time": "10:00",
    })
    assert backwards.status_code == 400
