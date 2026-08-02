import pytest
from app.budget import goal_customization as gc


def test_known_tokens_are_valid():
    assert gc.is_valid_icon("flame") and gc.is_valid_color("pine")
    assert not gc.is_valid_icon("nope") and not gc.is_valid_color("chartreuse")


def test_validate_allows_none_and_rejects_unknown():
    gc.validate_icon(None); gc.validate_color(None)  # no raise
    gc.validate_icon("tag"); gc.validate_color("honey")  # no raise
    with pytest.raises(ValueError):
        gc.validate_icon("bogus")
    with pytest.raises(ValueError):
        gc.validate_color("bogus")


def test_catalog_shape(client):
    body = client.get("/api/goal-customization/catalog").json()
    tokens = {i["token"] for i in body["icons"]}
    colors = {c["token"] for c in body["colors"]}
    assert {"tag", "flame", "chart"} <= tokens
    assert {"pine", "honey", "copper"} <= colors
    assert all("light" in c and "dark" in c for c in body["colors"])


def test_group_customization_upsert_and_clear(client, session):
    # unknown token rejected
    bad = client.put("/api/goal-groups/Trips/customization", json={"icon": "bogus"})
    assert bad.status_code == 400

    # set icon + color
    r = client.put("/api/goal-groups/Trips/customization", json={"icon": "plane", "color": "sky"})
    assert r.status_code == 200 and r.json() == {"name": "Trips", "icon": "plane", "color": "sky"}

    # read back
    got = client.get("/api/goal-groups/Trips/customization").json()
    assert got == {"name": "Trips", "icon": "plane", "color": "sky"}

    # partial update keeps the other field
    r = client.put("/api/goal-groups/Trips/customization", json={"icon": "car", "color": "sky"})
    assert r.json()["icon"] == "car"

    # clearing both deletes the row -> defaults (nulls)
    r = client.put("/api/goal-groups/Trips/customization", json={"icon": None, "color": None})
    assert r.json() == {"name": "Trips", "icon": None, "color": None}
    assert client.get("/api/goal-groups/Trips/customization").json() == {"name": "Trips", "icon": None, "color": None}


def test_group_customization_defaults_when_unset(client):
    got = client.get("/api/goal-groups/Nope/customization").json()
    assert got == {"name": "Nope", "icon": None, "color": None}


def test_group_customization_name_is_normalized(client):
    # A whitespace-variant group name must key the same settings as the
    # normalized Goal.group, so the read-model cascade still matches.
    gid = client.post("/api/goals", json={
        "name": "A", "kind": "numeric", "target": 10, "current": 1, "group": "Trips"}).json()["id"]
    r = client.put("/api/goal-groups/%20%20Trips%20%20/customization", json={"color": "sky"})
    assert r.json() == {"name": "Trips", "icon": None, "color": "sky"}
    # keyed under the stripped name (readable via the clean name)
    assert client.get("/api/goal-groups/Trips/customization").json()["color"] == "sky"
    # and it cascades to the member goal
    goal = next(g for g in client.get("/api/goals").json() if g["id"] == gid)
    assert goal["group_color"] == "sky" and goal["resolved_color"] == "sky"
