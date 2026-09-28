"""Remediation Wave 0 + 1: N1 auth-off console, N2 human_id uniqueness, N4 CSV."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base


# ---- N1: auth-off console must not 500 -------------------------------------


def test_n1_auth_off_facility_alerts_200(monkeypatch):
    monkeypatch.delenv("CARE_LADDER_AUTH", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    app = create_app(store=AuditStore())
    c = TestClient(app)
    r = c.get("/facility/alerts")
    assert r.status_code == 200, r.text
    assert "queue" in r.json()


# ---- N2: human_id never duplicates across restarts --------------------------


@pytest.fixture()
def engine():
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _client(engine):
    import sys

    sys.modules["care_ladder.api.app"]._FACILITY_STATES.clear()
    app = create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=engine))
    return TestClient(app)


def _login(c):
    r = c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    assert r.status_code == 200


def test_n2_human_ids_unique_across_restart(engine, monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "n2-test")

    c1 = _client(engine)
    _login(c1)
    c1.post("/demo/run", json={"fixture": "facility_negative_reply"})
    ids1 = {c["human_id"] for c in c1.get("/facility/cases").json()["open"]}
    assert ids1

    c2 = _client(engine)  # fresh process state, same DB
    _login(c2)
    new_iid = c2.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]
    all2 = c2.get("/facility/cases").json()["open"]
    ids2 = [c["human_id"] for c in all2]
    assert len(ids2) == len(set(ids2)), f"duplicate human ids: {ids2}"
    new_case = next(c for c in all2 if c["incident_id"] == new_iid)
    assert new_case["human_id"] not in ids1, "restart reissued a used human id"
    assert new_case["human_id"] == "CL-0002"


# ---- N4: CSV opened column + formula sanitation -----------------------------


def test_n4_csv_opened_and_formula_sanitize(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "n4-test")
    c = _client(create_engine_from_url("sqlite:///:memory:"))
    # engine above wasn't create_all'ed; use the fixture-free path via shared state
    # Simpler: reuse the engine fixture pattern inline
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    c = _client(eng)
    _login(c)
    iid = c.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]
    case = next(x for x in c.get("/facility/cases").json()["open"] if x["incident_id"] == iid)
    r = c.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": '=HYPERLINK("http://evil.example","Resident fine")'},
    )
    assert r.status_code == 200

    csv_text = c.get("/facility/audit/export.csv").text
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    row = next(x for x in rows if x["incident_id"] == iid)
    assert row["opened"], "opened column must be populated"
    assert not row["documentation"].startswith("="), "formula must be sanitized"
    assert row["documentation"].startswith("'"), "sanitized with leading apostrophe"
