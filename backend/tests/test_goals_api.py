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


def test_progress_negative_add_clamps_at_zero(client, session):
    gid = client.post("/api/goals", json={"name": "Reps", "kind": "numeric", "target": 100, "current": 10}).json()["id"]
    r = client.patch(f"/api/goals/{gid}/progress", json={"add": -4})
    assert r.status_code == 200 and r.json()["current_value"] == 6.0
    r = client.patch(f"/api/goals/{gid}/progress", json={"add": -50})
    assert r.status_code == 200 and r.json()["current_value"] == 0.0
    # Explicit sets are not clamped — negative values stay representable.
    r = client.patch(f"/api/goals/{gid}/progress", json={"current": -5})
    assert r.status_code == 200 and r.json()["current_value"] == -5.0


def test_update_goal_step(client, session):
    gid = client.post("/api/goals", json={"name": "Pushups", "kind": "numeric", "target": 100, "step": 1}).json()["id"]
    r = client.patch(f"/api/goals/{gid}", json={"step": 5})
    assert r.status_code == 200 and r.json()["step"] == 5.0
    assert client.get("/api/goals").json()[0]["step"] == 5.0
    assert client.patch(f"/api/goals/{gid}", json={"step": 0}).status_code == 400
    assert client.patch(f"/api/goals/{gid}", json={"step": -3}).status_code == 400


def test_progress_add_then_delete(client, session):
    gid = client.post("/api/goals", json={"name": "Trip", "kind": "save", "target": 2000, "current": 900}).json()["id"]
    r = client.patch(f"/api/goals/{gid}/progress", json={"add": 200})
    assert r.status_code == 200 and r.json()["current_value"] == 1100.0
    assert client.delete(f"/api/goals/{gid}").status_code == 204
    assert client.get("/api/goals").json() == []
    archived = client.get("/api/goals", params={"archived": True}).json()
    assert len(archived) == 1 and archived[0]["id"] == gid
    assert archived[0]["archived_at"] is not None


def test_rename_and_end_goal_group_are_atomic_and_preserve_history(client, session):
    first = client.post("/api/goals", json={
        "name": "Bench", "kind": "numeric", "target": 225, "current": 185, "group": "Lifts",
    }).json()
    second = client.post("/api/goals", json={
        "name": "Squat", "kind": "numeric", "target": 315, "current": 275, "group": "Lifts",
    }).json()
    ids = [first["id"], second["id"]]
    client.patch(f"/api/goals/{first['id']}/progress", json={"add": 5})

    renamed = client.patch("/api/goal-groups", json={"goal_ids": ids, "name": "Big Three"})
    assert renamed.status_code == 200
    assert {goal["group"] for goal in renamed.json()} == {"Big Three"}

    ended = client.post("/api/goal-groups/end", json={"goal_ids": ids})
    assert ended.status_code == 200
    assert ended.json() == ids
    assert client.get("/api/goals").json() == []
    archived = client.get("/api/goals", params={"archived": True}).json()
    archived_by_id = {goal["id"]: goal for goal in archived}
    assert archived_by_id[first["id"]]["history"]
    assert archived_by_id[first["id"]]["group"] == "Big Three"


def test_goal_group_action_rejects_stale_ids_without_partial_update(client, session):
    goal = client.post("/api/goals", json={
        "name": "Bench", "kind": "numeric", "target": 225, "group": "Lifts",
    }).json()
    response = client.patch("/api/goal-groups", json={
        "goal_ids": [goal["id"], 99999], "name": "Renamed",
    })
    assert response.status_code == 400
    assert client.get("/api/goals").json()[0]["group"] == "Lifts"


def test_reset_streak_restarts_today(client, session):
    gid = client.post("/api/goals", json={"name": "Sober", "kind": "streak", "since": "2026-06-01", "target": 30}).json()["id"]
    r = client.post(f"/api/goals/{gid}/reset")
    assert r.status_code == 200 and r.json()["days"] == 0


def test_update_goal_target(client, session):
    gid = client.post("/api/goals", json={"name": "Trip", "kind": "save", "target": 2000, "current": 900}).json()["id"]
    r = client.patch(f"/api/goals/{gid}", json={"target": 2500})
    assert r.json()["target"] == 2500.0 and r.json()["pct"] == 36.0


def test_create_weekly_spend_cap_redirects_to_budgets(client, session):
    resp = client.post("/api/goals", json={"name": "Eat wk", "kind": "spend_cap",
                                            "target": 100, "category": "EATING_OUT", "period": "weekly"})
    assert resp.status_code == 400
    assert "Budgets" in resp.json()["detail"]


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


class _FrozenWednesday(date):
    @classmethod
    def today(cls):
        return date(2026, 7, 22)  # a Wednesday; the week runs Sun 7/19 – Sat 7/25


def test_week_view_hides_next_week_while_current_week_has_days_left(client, session, monkeypatch):
    from app.budget.services import goals as goals_svc
    monkeypatch.setattr(goals_svc, "date", _FrozenWednesday)

    made = client.post("/api/goals", json={"name": "Retinol", "kind": "numeric", "target": 3,
                                           "period": "weekly", "weekly_days": ["monday", "friday"]}).json()
    goal = session.get(Goal, made["id"])
    goal.created_at = datetime(2026, 7, 21)  # Tuesday, after this week's Monday
    session.add(goal); session.commit()

    dates = [task["scheduled_for"] for task in client.get("/api/goal-tasks", params={"scope": "week"}).json()
             if task["goal_id"] == goal.id]
    assert dates == ["2026-07-24"]  # this week's Friday only — nothing from next week


def test_week_view_falls_back_to_next_week_when_created_after_last_scheduled_day(client, session, monkeypatch):
    from app.budget.services import goals as goals_svc
    monkeypatch.setattr(goals_svc, "date", _FrozenWednesday)

    made = client.post("/api/goals", json={"name": "Retinol", "kind": "numeric", "target": 3,
                                           "period": "weekly", "weekly_days": ["monday"]}).json()
    goal = session.get(Goal, made["id"])
    goal.created_at = datetime(2026, 7, 21)  # Tuesday, after this week's only scheduled day
    session.add(goal); session.commit()

    dates = [task["scheduled_for"] for task in client.get("/api/goal-tasks", params={"scope": "week"}).json()
             if task["goal_id"] == goal.id]
    assert dates == ["2026-07-27"]  # next Monday, so the checklist isn't empty


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
    resp = client.post("/api/goals", json={"name": "Weight", "kind": "numeric",
                                           "target": 180, "current": 200, "direction": "under"})
    assert resp.status_code == 201
    assert resp.json()["direction"] == "under" and resp.json()["anchor_value"] == 200
    assert resp.json()["status"] == "active" and resp.json()["pct"] == 0
    updated = client.patch(f"/api/goals/{resp.json()['id']}/progress", json={"current": 190})
    assert updated.json()["pct"] == 50.0


def test_flexible_financial_goal_round_trips(client, session):
    account = _account(session, current_balance=2500.0)
    response = client.post("/api/goals", json={
        "name": "Emergency fund", "kind": "financial",
        "financial_metric": "account_balance", "financial_rule": "reach",
        "target": 5000, "account_ids": [account.id],
    })
    assert response.status_code == 201
    goal = response.json()
    assert goal["financial_metric"] == "account_balance"
    assert goal["account_ids"] == [account.id]
    assert goal["current_value"] == 2500 and goal["pct"] == 50


def test_manual_financial_goal_round_trips_without_an_account(client, session):
    response = client.post("/api/goals", json={
        "name": "Vacation fund", "kind": "financial", "financial_source": "manual",
        "financial_metric": "account_balance", "financial_rule": "reach",
        "target": 2000, "current": 250, "step": 25,
    })
    assert response.status_code == 201
    goal = response.json()
    assert goal["financial_source"] == "manual" and goal["account_ids"] == []
    assert goal["current_value"] == 250 and goal["unit"] == "$"

    updated = client.patch(f"/api/goals/{goal['id']}/progress", json={"add": 25})
    assert updated.status_code == 200 and updated.json()["current_value"] == 275


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


def test_goal_icon_color_patch_and_resolution(client, session):
    gid = client.post("/api/goals", json={"name": "Reps", "kind": "numeric", "target": 100, "current": 10}).json()["id"]
    # defaults before any customization
    g = client.get("/api/goals").json()[0]
    assert g["icon"] is None and g["color"] is None
    assert g["resolved_icon"] == "chart" and g["resolved_color"] == "pine"

    # unknown token rejected
    assert client.patch(f"/api/goals/{gid}", json={"color": "bogus"}).status_code == 400

    # set overrides
    r = client.patch(f"/api/goals/{gid}", json={"icon": "flame", "color": "rose"})
    assert r.status_code == 200 and r.json()["resolved_icon"] == "flame" and r.json()["resolved_color"] == "rose"

    # clear color -> back to default
    r = client.patch(f"/api/goals/{gid}", json={"color": None})
    assert r.json()["color"] is None and r.json()["resolved_color"] == "pine"


def test_streak_default_color_is_honey(client, session):
    client.post("/api/goals", json={"name": "Meditate", "kind": "streak"})
    g = client.get("/api/goals").json()[0]
    assert g["resolved_icon"] == "flame" and g["resolved_color"] == "honey"


def test_group_color_cascades_to_members(client, session):
    a = client.post("/api/goals", json={"name": "A", "kind": "numeric", "target": 10, "current": 1, "group": "Trips"}).json()["id"]
    b = client.post("/api/goals", json={"name": "B", "kind": "numeric", "target": 10, "current": 1, "group": "Trips"}).json()["id"]
    client.put("/api/goal-groups/Trips/customization", json={"icon": "plane", "color": "sky"})

    goals = {g["id"]: g for g in client.get("/api/goals").json()}
    # cascade: neither goal set its own color -> inherits group color
    assert goals[a]["resolved_color"] == "sky" and goals[a]["group_color"] == "sky" and goals[a]["group_icon"] == "plane"
    # per-goal override wins over the cascade
    client.patch(f"/api/goals/{b}", json={"color": "rose"})
    goals = {g["id"]: g for g in client.get("/api/goals").json()}
    assert goals[b]["resolved_color"] == "rose" and goals[b]["group_color"] == "sky"


def test_group_settings_follow_rename_and_end(client, session):
    a = client.post("/api/goals", json={"name": "A", "kind": "numeric", "target": 10, "current": 1, "group": "Trips"}).json()["id"]
    client.put("/api/goal-groups/Trips/customization", json={"color": "sky"})
    # rename Trips -> Journeys carries the settings
    client.patch("/api/goal-groups", json={"goal_ids": [a], "name": "Journeys"})
    assert client.get("/api/goal-groups/Journeys/customization").json()["color"] == "sky"
    assert client.get("/api/goal-groups/Trips/customization").json()["color"] is None
    # ending the group deletes its settings
    client.post("/api/goal-groups/end", json={"goal_ids": [a]})
    assert client.get("/api/goal-groups/Journeys/customization").json()["color"] is None
