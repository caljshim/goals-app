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
