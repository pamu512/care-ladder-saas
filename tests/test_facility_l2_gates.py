"""Layer 2 gates: plan packaging, retention default/extension, handoff audit,
Teams-first delivery preference, persistence across restarts."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.billing.plans import tenant_can_use_layer2
from care_ladder.channels.router import TeamsAdapter
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base
from care_ladder.facility.routing import preferred_notifier
from care_ladder.channels.notify import NotifyChannelAdapter


# -- plan gate ---------------------------------------------------------------


def test_layer2_plan_matrix():
    assert tenant_can_use_layer2({"mode": "facility", "plan": "facility_growth", "status": "active"})
    assert tenant_can_use_layer2({"mode": "facility", "plan": "demo", "status": "demo"})
    assert not tenant_can_use_layer2({"mode": "facility", "plan": "facility_starter", "status": "active"})
    assert not tenant_can_use_layer2({"mode": "home", "plan": "home", "status": "active"})
    assert not tenant_can_use_layer2({"mode": "facility", "plan": "facility_growth", "status": "past_due"})


@pytest.fixture()
def client(monkeypatch):
    import sys

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "l2-gates-test")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    appmod = sys.modules["care_ladder.api.app"]
    appmod._FACILITY_STATES.clear()
    appmod._SETTINGS_OVERRIDES.clear()
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def test_cover_blocked_for_home_tenant(client):
    r = client.post(
        "/auth/login",
        json={"email": "demo@careladder.local", "password": "demo-pass-home"},
    )
    assert r.status_code == 200
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_call"},
    )
    assert r.status_code == 403  # home tenant: facility console 403 / layer 2 gate


def test_starter_tenant_cover_blocked(client):
    """facility_starter does not get layer 2 (PRD packaging lock)."""
    _facility_login(client)
    # mutate the in-memory billing record the gate reads
    transport = client._transport
    transport.app.state.billing_tenants["demo-facility"]["plan"] = "facility_starter"
    try:
        r = client.post(
            "/facility/staff/demo-facility-maria/cover",
            json={"cover": "on_call"},
        )
        assert r.status_code == 403
        assert "Facility Growth" in r.json()["detail"]
    finally:
        transport.app.state.billing_tenants["demo-facility"]["plan"] = "demo"


def test_starter_tenant_handoff_blocked(client):
    _facility_login(client)
    transport = client._transport
    transport.app.state.billing_tenants["demo-facility"]["plan"] = "facility_starter"
    try:
        r = client.post(
            "/facility/cases/whatever/handoff",
            json={"note": "check the left side at 2pm"},
        )
        assert r.status_code == 403
        assert "Facility Growth" in r.json()["detail"]
    finally:
        transport.app.state.billing_tenants["demo-facility"]["plan"] = "demo"


# -- retention ---------------------------------------------------------------


def test_retention_defaults_to_3_years(client):
    _facility_login(client)
    settings = client.get("/facility/settings").json()
    assert settings["audit_retention_years"] == 3


def test_owner_can_extend_retention(client):
    _facility_login(client)
    r = client.patch(
        "/facility/settings",
        json={"audit_retention_years": 7},
    )
    assert r.status_code == 200, r.text
    assert r.json()["audit_retention_years"] == 7
    assert client.get("/facility/settings").json()["audit_retention_years"] == 7


def test_retention_cannot_shorten_below_default(client):
    _facility_login(client)
    client.patch("/facility/settings", json={"audit_retention_years": 7})
    r = client.patch("/facility/settings", json={"audit_retention_years": 1})
    assert r.status_code == 422


def test_retention_bounds_422(client):
    _facility_login(client)
    assert client.patch("/facility/settings", json={"audit_retention_years": 11}).status_code == 422
    assert client.patch("/facility/settings", json={"audit_retention_years": "x"}).status_code == 422


# -- handoff notes + audit ----------------------------------------------------


def test_handoff_note_appends_to_case_and_audit(client):
    _facility_login(client)
    iid = client.post(
        "/demo/run", json={"fixture": "facility_negative_reply"}
    ).json()["incident_id"]
    cases = client.get("/facility/cases").json()["open"]
    case = next(c for c in cases if c["incident_id"] == iid)
    r = client.post(
        f"/facility/cases/{case['id']}/handoff",
        json={"note": "Margaret prefers the blue blanket; ask before repositioning.", "by_staff_id": "demo-facility-maria"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["case"]
    assert len(body["handoffs"]) == 1
    assert body["handoffs"][0]["by_name"] == "Maria G."
    # audit trail carries the handoff
    inc = client.get(f"/incidents/{iid}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "handoff_note" in tools


def test_handoff_note_rejects_short_note(client):
    _facility_login(client)
    iid = client.post(
        "/demo/run", json={"fixture": "facility_negative_reply"}
    ).json()["incident_id"]
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    r = client.post(f"/facility/cases/{case['id']}/handoff", json={"note": "hi"})
    assert r.status_code == 422


def test_handoff_note_rejects_unknown_case(client):
    _facility_login(client)
    r = client.post("/facility/cases/nope/handoff", json={"note": "a reasonable note"})
    assert r.status_code == 422


# -- Teams-first delivery preference ------------------------------------------


def test_preferred_notifier_teams_when_env_set(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/x")
    n = preferred_notifier()
    assert isinstance(n, TeamsAdapter)


def test_preferred_notifier_slack_path_when_teams_unset(monkeypatch):
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    n = preferred_notifier()
    assert isinstance(n, NotifyChannelAdapter)


# -- persistence across restarts ------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _pg_client(engine, restart=False):
    import sys

    mod = sys.modules["care_ladder.api.app"]
    mod._FACILITY_STATES.clear()
    mod._SETTINGS_OVERRIDES.clear()
    application = create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=engine))
    return TestClient(application)


def _login(c):
    r = c.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def test_cover_and_handoff_survive_restart(engine, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "l2-persist-test")
    c1 = _pg_client(engine)
    _login(c1)
    iid = c1.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]
    case = next(c for c in c1.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    r = c1.post(
        "/facility/staff/demo-facility-jamie/cover",
        json={"cover": "backup"},
    )
    assert r.status_code == 200, r.text
    r = c1.post(
        f"/facility/cases/{case['id']}/handoff",
        json={"note": "Watch the door alarm; it sticks when latched.", "by_staff_id": "demo-facility-jamie"},
    )
    assert r.status_code == 200, r.text

    c2 = _pg_client(engine, restart=True)
    _login(c2)
    staff = {s["id"]: s for s in c2.get("/facility/staff").json()["staff"]}
    assert staff["demo-facility-jamie"]["cover"] == "backup"
    cases2 = c2.get("/facility/cases").json()["open"]
    case2 = next(c for c in cases2 if c["incident_id"] == iid)
    assert len(case2["handoffs"]) == 1
    assert case2["handoffs"][0]["by_name"] == "Jamie D."
