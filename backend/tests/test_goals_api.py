from datetime import date, datetime, timedelta

from app.budget.models import Account, Goal, PlaidItem


def _account(session, **kw):
    item = PlaidItem(plaid_item_id="i1", access_token="t")
    session.add(item); session.commit(); session.refresh(item)
    d = dict(plaid_account_id="a1", item_id=item.id, name="Ally Savings",
             type="depository", current_balance=3412.0)
    d.update(kw)
    a = Account(**d); session.add(a); session.commit(); session.refresh(a)
    return a


def test_create_and_list_goal(client, session):
    resp = client.post("/api/goals", json={"name": "Trip", "kind": "save", "target": 2000, "current": 900})
    assert resp.status_code == 201
    assert resp.json()["current_value"] == 900.0 and resp.json()["pct"] == 45.0
    listed = client.get("/api/goals").json()
    assert len(listed) == 1 and listed[0]["name"] == "Trip"


def test_save_goal_linked_to_account(client, session):
    a = _account(session)
    resp = client.post("/api/goals", json={"name": "Emergency", "kind": "save", "target": 5000, "account_id": a.id})
    assert resp.status_code == 201
    assert resp.json()["current_value"] == 3412.0 and resp.json()["linked_label"] == "Ally Savings"


def test_create_validation_is_400(client, session):
    resp = client.post("/api/goals", json={"name": "x", "kind": "spend_cap", "target": 100})
    assert resp.status_code == 400


def test_progress_add_then_delete(client, session):
    gid = client.post("/api/goals", json={"name": "Trip", "kind": "save", "target": 2000, "current": 900}).json()["id"]
    r = client.patch(f"/api/goals/{gid}/progress", json={"add": 200})
    assert r.status_code == 200 and r.json()["current_value"] == 1100.0
    assert client.delete(f"/api/goals/{gid}").status_code == 204
    assert client.get("/api/goals").json() == []


def test_reset_streak_restarts_today(client, session):
    gid = client.post("/api/goals", json={"name": "Sober", "kind": "streak", "since": "2026-06-01", "target": 30}).json()["id"]
    r = client.post(f"/api/goals/{gid}/reset")
    assert r.status_code == 200 and r.json()["days"] == 0


def test_update_goal_target(client, session):
    gid = client.post("/api/goals", json={"name": "Trip", "kind": "save", "target": 2000, "current": 900}).json()["id"]
    r = client.patch(f"/api/goals/{gid}", json={"target": 2500})
    assert r.json()["target"] == 2500.0 and r.json()["pct"] == 36.0


def test_create_weekly_spend_cap_round_trips_period(client, session):
    resp = client.post("/api/goals", json={"name": "Eat wk", "kind": "spend_cap",
                                            "target": 100, "category": "EATING_OUT", "period": "weekly"})
    assert resp.status_code == 201
    assert resp.json()["period"] == "weekly"


def test_weekly_goal_round_trips_preferred_day(client, session):
    resp = client.post("/api/goals", json={"name": "Church", "kind": "numeric",
                                            "target": 1, "period": "weekly", "weekly_day": "sunday"})
    assert resp.status_code == 201
    assert resp.json()["weekly_day"] == "sunday"

    updated = client.patch(f"/api/goals/{resp.json()['id']}", json={"weekly_day": "wednesday"})
    assert updated.status_code == 200
    assert updated.json()["weekly_day"] == "wednesday"


def test_weekly_goal_rejects_unknown_day(client, session):
    resp = client.post("/api/goals", json={"name": "Church", "kind": "numeric",
                                            "target": 1, "period": "weekly", "weekly_day": "someday"})
    assert resp.status_code == 400


def test_weekly_goal_supports_multiple_reminder_days(client, session):
    resp = client.post("/api/goals", json={"name": "Use retinol", "kind": "numeric",
                                            "target": 3, "period": "weekly",
                                            "weekly_days": ["friday", "monday", "wednesday"]})
    assert resp.status_code == 201
    assert resp.json()["weekly_days"] == ["monday", "wednesday", "friday"]

    updated = client.patch(f"/api/goals/{resp.json()['id']}",
                           json={"weekly_days": ["tuesday", "thursday"]})
    assert updated.status_code == 200
    assert updated.json()["weekly_days"] == ["tuesday", "thursday"]


def test_missed_goal_task_is_locked_without_manual_override(client, session):
    yesterday = date.today() - timedelta(days=1)
    weekday = yesterday.strftime("%A").lower()
    created = client.post("/api/goals", json={"name": "Scheduled task", "kind": "numeric",
                                                "target": 1, "period": "weekly",
                                                "weekly_days": [weekday]}).json()
    goal = session.get(Goal, created["id"])
    goal.created_at = datetime.combine(yesterday - timedelta(days=1), datetime.min.time())
    session.add(goal); session.commit()

    tasks = client.get("/api/goal-tasks", params={"scope": "week"}).json()
    missed = next(task for task in tasks if task["scheduled_for"] == yesterday.isoformat())
    assert missed["missed"] is True

    locked = client.patch(f"/api/goals/{goal.id}/checkin",
                          json={"scheduled_for": yesterday.isoformat(), "completed": True})
    assert locked.status_code == 400
    corrected = client.patch(f"/api/goals/{goal.id}/checkin",
                             json={"scheduled_for": yesterday.isoformat(), "completed": True,
                                   "allow_overdue": True})
    assert corrected.status_code == 200
    assert corrected.json()["completed"] is True


def test_week_view_includes_next_schedule_when_goal_created_near_week_end(client, session):
    current_week_start = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)
    next_monday = current_week_start + timedelta(days=8)
    created = client.post("/api/goals", json={"name": "Retinol", "kind": "numeric",
                                                "target": 3, "period": "weekly",
                                                "weekly_days": ["monday", "wednesday", "friday"]}).json()
    goal = session.get(Goal, created["id"])
    goal.created_at = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
    session.add(goal); session.commit()

    tasks = client.get("/api/goal-tasks", params={"scope": "week"}).json()
    retinol_dates = [task["scheduled_for"] for task in tasks if task["goal_id"] == goal.id]
    assert next_monday.isoformat() in retinol_dates


def test_custom_reset_settings_and_interval_round_trip(client, session):
    weekly = client.post("/api/goals", json={"name": "Train", "kind": "numeric", "target": 1,
                                              "period": "weekly", "weekly_reset_day": "monday",
                                              "reset_time": "06:30"})
    assert weekly.status_code == 201
    assert weekly.json()["weekly_reset_day"] == "monday"
    assert weekly.json()["reset_time"] == "06:30"

    interval = client.post("/api/goals", json={"name": "Face mask", "kind": "numeric", "target": 1,
                                                "period": "interval", "interval_days": 3,
                                                "reset_time": "21:00"})
    assert interval.status_code == 201
    assert interval.json()["interval_days"] == 3

    invalid_month = client.post("/api/goals", json={"name": "Review", "kind": "numeric", "target": 1,
                                                     "period": "monthly", "monthly_reset_day": 29})
    assert invalid_month.status_code == 400


def test_spend_cap_rejects_once_period(client, session):
    resp = client.post("/api/goals", json={"name": "x", "kind": "spend_cap",
                                            "target": 100, "category": "EATING_OUT", "period": "once"})
    assert resp.status_code == 400


def test_numeric_under_goal_round_trips(client, session):
    resp = client.post("/api/goals", json={"name": "Subs", "kind": "numeric",
                                           "target": 100, "current": 80, "direction": "under"})
    assert resp.status_code == 201
    assert resp.json()["direction"] == "under" and resp.json()["status"] == "under"


def test_goal_step_defaults_and_round_trips(client, session):
    r1 = client.post("/api/goals", json={"name": "Books", "kind": "numeric", "target": 12, "current": 0}).json()
    assert r1["step"] == 1.0  # default
    r2 = client.post("/api/goals", json={"name": "Fund", "kind": "save", "target": 5000,
                                         "current": 0, "step": 100}).json()
    assert r2["step"] == 100.0


def test_stepper_add_uses_signed_amount(client, session):
    gid = client.post("/api/goals", json={"name": "Books", "kind": "numeric", "target": 12, "current": 3}).json()["id"]
    up = client.patch(f"/api/goals/{gid}/progress", json={"add": 1}).json()
    assert up["current_value"] == 4.0
    down = client.patch(f"/api/goals/{gid}/progress", json={"add": -1}).json()
    assert down["current_value"] == 3.0


def test_raise_endpoint_logs_milestone(client, session):
    gid = client.post("/api/goals", json={"name": "Bench", "kind": "numeric", "target": 315, "current": 315}).json()["id"]
    r = client.post(f"/api/goals/{gid}/raise", json={"target": 335})
    assert r.status_code == 200
    assert r.json()["target"] == 335.0
    assert [m["value"] for m in r.json()["milestones"]] == [315.0]


def test_update_goal_edits_name_and_group(client, session):
    gid = client.post("/api/goals", json={"name": "Bench", "kind": "numeric", "target": 315, "current": 275}).json()["id"]
    r = client.patch(f"/api/goals/{gid}", json={"name": "Bench press", "group": "1000 CLUB"})
    assert r.status_code == 200
    assert r.json()["name"] == "Bench press" and r.json()["group"] == "1000 CLUB"


def test_missing_goal_404(client, session):
    assert client.delete("/api/goals/999").status_code == 404
    assert client.patch("/api/goals/999", json={"target": 1}).status_code == 404
    assert client.post("/api/goals/999/reset").status_code == 404
