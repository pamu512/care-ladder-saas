"""ROI #3: /facility/alerts resident_resolved must not hardcode room 204."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app, _facility_state
from care_ladder.audit.store import AuditStore
from care_ladder.facility.models import Case
from care_ladder.models import AuditEvent, CueEvent, Incident


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "alerts-honesty")
    app = create_app(store=AuditStore())
    return TestClient(app)


def _login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def _tenant_store(client) -> AuditStore:
    """Force-create / return the auth-on per-tenant AuditStore."""
    # Touch an authed endpoint so create_app wires tenant_stores.
    client.get("/facility/alerts")
    stores = getattr(client.app.state, "tenant_stores", {})
    store = stores.get("demo-facility")
    assert store is not None, "expected demo-facility tenant store after login"
    return store


def _seed_resolved_positive(store, incident_id: str) -> Incident:
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "custom"})
    inc = Incident(
        id=incident_id,
        household_id="demo-facility",
        cue=cue,
        status="resolved",
        events=[
            AuditEvent(tool="speaker_prompt", detail={"reply_class": "positive"}),
        ],
    )
    store.save(inc)
    return inc


def test_positive_fixture_preserves_margaret_not_null_subject(client):
    """Assisted-living positive fixture must keep Margaret Hale after GET rebuild."""
    _login(client)
    r = client.post("/demo/run", json={"fixture": "facility_positive_reply"})
    assert r.status_code == 200, r.text
    iid = r.json()["incident_id"]
    body = client.get("/facility/alerts").json()
    rows = [a for a in body["resident_resolved"] if a["incident_id"] == iid]
    assert len(rows) == 1
    assert rows[0]["subject_display_name"] == "Margaret Hale"
    assert rows[0].get("room_label") in {"204", "Room 204"} or rows[0].get("place_label")


def test_resident_resolved_keeps_prior_subject_not_invented_204(client):
    """Prior RR entry for a custom room must survive GET rebuild (no invent-204)."""
    _login(client)
    store = _tenant_store(client)
    _seed_resolved_positive(store, "inc-rr-1")

    state = _facility_state(
        "demo-facility", getattr(client.app.state, "pg_session_factory", None)
    )
    state.resident_resolved = [
        {
            "incident_id": "inc-rr-1",
            "room_label": "classroom_1",
            "place_label": "Classroom 1",
            "subject_display_name": "Nora Kim",
            "subject_kind": "child",
            "reply_class": "positive",
        }
    ]

    body = client.get("/facility/alerts").json()
    rows = [r for r in body["resident_resolved"] if r["incident_id"] == "inc-rr-1"]
    assert len(rows) == 1
    assert rows[0]["room_label"] == "classroom_1"
    assert rows[0]["place_label"] == "Classroom 1"
    assert rows[0]["subject_display_name"] == "Nora Kim"
    assert rows[0]["room_label"] != "204"


def test_resident_resolved_derives_from_case_row(client):
    _login(client)
    store = _tenant_store(client)
    _seed_resolved_positive(store, "inc-rr-case")

    state = _facility_state(
        "demo-facility", getattr(client.app.state, "pg_session_factory", None)
    )
    case = Case.open_from_incident(
        incident_id="inc-rr-case",
        tenant_id="demo-facility",
        room_label="gym",
        origin="from_silence",
        priority="P2",
        human_id="CL-TEST-1",
        subject_display_name="Dana Patel",
        subject_kind="patient",
        subject_id="pt-dp-4",
    )
    case.place_label = "Gym"
    case.state = "closed"
    state.open_case(case)

    body = client.get("/facility/alerts").json()
    rows = [r for r in body["resident_resolved"] if r["incident_id"] == "inc-rr-case"]
    assert len(rows) == 1
    assert rows[0]["room_label"] == "gym"
    assert rows[0]["place_label"] == "Gym"
    assert rows[0]["subject_display_name"] == "Dana Patel"
