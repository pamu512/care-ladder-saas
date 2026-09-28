"""Slice 5: facility state persists across restarts when Postgres is configured.

The gap: FacilityState was process-local, so cases/staff/break state reset on
every deploy. When a session factory exists (DATABASE_URL set), the facility
console must read/write through FacilityRepository.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base


@pytest.fixture()
def engine():
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _client(engine, store=None, restart=False):
    import sys

    mod = sys.modules["care_ladder.api.app"]
    mod._FACILITY_STATES.clear()  # fresh process state (restart or new test)
    application = create_app(store=store or AuditStore(), pg_session_factory=sessionmaker(bind=engine))
    return TestClient(application)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def test_case_survives_restart(engine, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "slice5-test")

    c1 = _client(engine)
    _facility_login(c1)
    r = c1.post("/demo/run", json={"fixture": "facility_negative_reply"})
    assert r.status_code == 200
    iid = r.json()["incident_id"]
    cases = c1.get("/facility/cases").json()
    assert any(c["incident_id"] == iid for c in cases["open"])

    # "restart": brand-new app instance sharing the same database
    c2 = _client(engine)
    _facility_login(c2)
    cases2 = c2.get("/facility/cases").json()
    assert any(c["incident_id"] == iid for c in cases2["open"]), "case must survive restart"


def test_staff_break_and_close_survive_restart(engine, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "slice5-test")

    c1 = _client(engine)
    _facility_login(c1)
    iid = c1.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]

    staff = c1.get("/facility/staff").json()["staff"]
    assert len(staff) >= 4  # roster from Postgres (bootstrap-seeded shape)
    maria = next(s for s in staff if "Maria" in s["display_name"])
    r = c1.post(f"/facility/staff/{maria['id']}/break", json={"on_break": True, "minutes": 15})
    assert r.status_code == 200

    case = next(c for c in c1.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    c1.post(f"/facility/cases/{case['id']}/ack", json={})
    r = c1.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Resident dizzy; vitals stable; MD notified this shift."},
    )
    assert r.status_code == 200

    c2 = _client(engine, restart=True)  # restart
    _facility_login(c2)
    staff2 = c2.get("/facility/staff").json()["staff"]
    m2 = next(s for s in staff2 if s["id"] == maria["id"])
    assert m2["status"] == "on_break", "break state must survive restart"
    cases2 = c2.get("/facility/cases").json()
    closed = [c for c in cases2["closed_today"] if c["id"] == case["id"]]
    assert closed and closed[0]["documentation"], "closed case + docs must survive restart"


def test_resident_resolved_derived_from_incident_store(engine, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "slice5-test")

    c1 = _client(engine)
    _facility_login(c1)
    iid = c1.post("/demo/run", json={"fixture": "facility_positive_reply"}).json()["incident_id"]
    assert any(a["incident_id"] == iid for a in c1.get("/facility/alerts").json()["resident_resolved"])

    c2 = _client(engine, restart=True)  # restart
    _facility_login(c2)
    rr = c2.get("/facility/alerts").json()["resident_resolved"]
    assert any(a["incident_id"] == iid for a in rr), "resident-resolved must derive from incidents, not memory"
