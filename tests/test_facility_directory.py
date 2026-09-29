"""People, Places, and Channels directory: honest read-only facility views."""
from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.facility.directory import (
    build_channels,
    build_people,
    build_places,
    plan_for_type,
    seed_people,
)
from care_ladder.facility.models import Case
from care_ladder.facility.service import FacilityState
from care_ladder.plan_loader import load_care_plan


def _client(monkeypatch, secret="dir-test"):
    import sys

    appmod = sys.modules["care_ladder.api.app"]
    appmod._FACILITY_STATES.clear()
    appmod._SETTINGS_OVERRIDES.clear()
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", secret)
    for var in (
        "SLACK_WEBHOOK_URL",
        "TEAMS_WEBHOOK_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "WHATSAPP_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_TO",
    ):
        monkeypatch.delenv(var, raising=False)
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def _home_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "demo@careladder.local", "password": "demo-pass-home"},
    )
    assert r.status_code == 200


def test_seed_people_match_demo_fixtures():
    al = seed_people("assisted_living")
    assert any(p["display_name"] == "Margaret Hale" for p in al)
    assert all("checkins" not in p for p in al)
    kids = seed_people("daycare_kids")
    assert any(p["display_name"] == "Nora Kim" for p in kids)
    rehab = seed_people("rehab")
    assert any(p["display_name"] == "Dana Patel" for p in rehab)


def test_build_people_merges_open_case_status():
    state = FacilityState()
    case = Case.open_from_incident(
        incident_id="inc-neg",
        tenant_id="t1",
        room_label="204",
        origin="from_negative_reply",
        priority="P1",
        human_id="CL-0001",
        subject_display_name="Margaret Hale",
        subject_kind="resident",
        subject_id="res-204",
    )
    case.place_label = "204"
    state.cases[case.id] = case
    rows = build_people(state, facility_type="assisted_living")
    meg = next(p for p in rows if p["display_name"] == "Margaret Hale")
    assert meg["place_label"] == "204"
    assert meg["status"] == "incident open"
    assert meg["last_response"] == "negative"
    assert "checkins" not in meg
    assert "pendant" not in meg


def test_build_people_positive_reply_is_ok():
    state = FacilityState()
    state.resident_resolved.append(
        {
            "incident_id": "inc-ok",
            "place_label": "Room 204",
            "subject_display_name": "Margaret Hale",
            "reply_class": "positive",
        }
    )
    rows = build_people(state, facility_type="assisted_living")
    meg = next(p for p in rows if p["display_name"] == "Margaret Hale")
    assert meg["status"] == "ok"
    assert meg["last_response"] == "positive"


def test_build_places_uses_plan_zones_not_invented_cameras():
    plan = load_care_plan(plan_for_type("assisted_living"))
    rows = build_places(FacilityState(), AuditStore(), plan)
    assert rows
    common = next(p for p in rows if p["id"] == "common_room")
    assert common["zone_kind"] == "common"
    assert common["privacy"] in ("blur", "silhouette")
    assert common["status"] == "configured"
    assert "cam-" not in (common.get("camera_label") or "")
    assert "watching" not in common["status"]


def test_build_places_marks_live_case_place():
    plan = load_care_plan(plan_for_type("assisted_living"))
    state = FacilityState()
    case = Case.open_from_incident(
        incident_id="inc-1",
        tenant_id="t1",
        room_label="204",
        origin="from_silence",
        priority="P2",
        human_id="CL-0002",
        subject_display_name="Margaret Hale",
        subject_kind="resident",
        subject_id="res-204",
    )
    case.place_label = "204"
    state.cases[case.id] = case
    rows = build_places(state, AuditStore(), plan)
    live = next(p for p in rows if p["place_label"] in ("204", "Room 204"))
    assert live["status"] == "incident open"


def test_build_channels_honest_stub_without_env():
    plan = load_care_plan(plan_for_type("assisted_living"))
    body = build_channels(plan, live_envs=[], store=AuditStore())
    ids = [c["id"] for c in body["channels"]]
    assert ids == ["slack", "teams", "whatsapp", "telegram"]
    slack = body["channels"][0]
    assert slack["state"] == "configured · stub"
    assert slack["live"] is False
    assert slack["plan_enabled"] is True
    assert slack.get("target") == "#floor-ops"
    assert "delivery_ok" not in slack
    assert "median_ms" not in slack
    teams = body["channels"][1]
    assert teams["state"] == "not configured"
    assert body["deliveries"] == []


def test_build_channels_live_env_is_connected():
    plan = load_care_plan(plan_for_type("assisted_living"))
    body = build_channels(plan, live_envs=["slack"], store=AuditStore())
    slack = body["channels"][0]
    assert slack["live"] is True
    assert slack["state"].startswith("connected")


def test_people_places_channels_require_session(monkeypatch):
    client = _client(monkeypatch)
    for path in ("/facility/people", "/facility/places", "/facility/channels"):
        assert client.get(path).status_code == 401


def test_home_tenant_blocked_from_directory(monkeypatch):
    client = _client(monkeypatch)
    _home_login(client)
    for path in ("/facility/people", "/facility/places", "/facility/channels"):
        assert client.get(path).status_code == 403


def test_people_api_seeds_and_reflects_negative_reply(monkeypatch):
    client = _client(monkeypatch)
    _facility_login(client)
    seeded = client.get("/facility/people")
    assert seeded.status_code == 200
    names = [p["display_name"] for p in seeded.json()["people"]]
    assert "Margaret Hale" in names
    assert client.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    people = client.get("/facility/people").json()["people"]
    meg = next(p for p in people if p["display_name"] == "Margaret Hale")
    assert meg["status"] == "incident open"
    assert meg["last_response"] == "negative"
    assert meg["place_label"]
    assert "checkins" not in meg


def test_places_api_includes_plan_zone_and_case_place(monkeypatch):
    client = _client(monkeypatch)
    _facility_login(client)
    before = client.get("/facility/places")
    assert before.status_code == 200
    ids = [p["id"] for p in before.json()["places"]]
    assert "common_room" in ids
    assert client.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    places = client.get("/facility/places").json()["places"]
    assert any(p["place_label"] in ("204", "Room 204") and p["status"] == "incident open" for p in places)


def test_channels_api_lists_envs_and_real_deliveries(monkeypatch):
    client = _client(monkeypatch)
    _facility_login(client)
    empty = client.get("/facility/channels")
    assert empty.status_code == 200
    body = empty.json()
    assert [c["id"] for c in body["channels"]] == ["slack", "teams", "whatsapp", "telegram"]
    assert body["channels"][0]["state"] == "configured · stub"
    assert all("median_ms" not in c and "delivery_ok" not in c for c in body["channels"])
    assert body["deliveries"] == []
    assert client.post("/demo/run", json={"fixture": "facility_notify_silence"}).status_code == 200
    after = client.get("/facility/channels").json()
    assert after["deliveries"]
    row = after["deliveries"][0]
    assert row["channel"]
    assert row["result"] in ("stub", "delivered", "failed", "waiting for ack")
    assert "ack" in row


def test_channels_api_connected_when_env_present(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/T/B/X")
    _facility_login(client)
    slack = client.get("/facility/channels").json()["channels"][0]
    assert slack["id"] == "slack"
    assert slack["live"] is True
    assert slack["state"].startswith("connected")


def test_directory_follows_facility_type_switch(monkeypatch):
    client = _client(monkeypatch)
    _facility_login(client)
    r = client.patch("/facility/settings", json={"facility_type": "daycare_kids"})
    assert r.status_code == 200
    people = client.get("/facility/people").json()["people"]
    assert any(p["display_name"] == "Nora Kim" for p in people)
    places = client.get("/facility/places").json()["places"]
    assert any(p["id"] == "classroom_1" for p in places)


def test_facility_ui_wires_directory_nav_and_hooks(monkeypatch):
    client = _client(monkeypatch)
    _facility_login(client)
    html = client.get("/ui/facility/").text
    people_i = html.index('data-view="people"')
    places_i = html.index('data-view="places"')
    staff_i = html.index('data-view="staff"')
    channels_i = html.index('data-view="channels"')
    assert people_i < places_i < staff_i < channels_i
    assert "Places · cameras" in html
    assert 'id="view-people"' in html
    assert 'id="view-places"' in html
    assert 'id="view-channels"' in html
    assert "people:[" in html and '"People"' in html
    assert "places:[" in html
    assert "channels:[" in html
    assert "/facility/people" in html
    assert "/facility/places" in html
    assert "/facility/channels" in html
    assert 'id="people-table"' in html
    assert 'id="places-table"' in html
    assert 'id="channel-grid"' in html
    assert 'id="channel-deliveries"' in html
    assert "coming soon" not in html.lower()
    assert "Median delivery" not in html
    assert "Delivery today" not in html
    assert "Send test page" not in html
    assert "\u2014" not in html
    assert "n/a" not in html
