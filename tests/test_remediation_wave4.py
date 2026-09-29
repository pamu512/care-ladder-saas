"""Remediation Wave 4: N5 classifier negation, N6 roster parity, N3 override survival."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base


# ---- N5: negation must not P1 ------------------------------------------------


def test_n5_negation_phrases():
    from care_ladder.facility.classify import classify_reply

    negatives_must_not = [
        "No, I don't need anything",
        "I don't need help",
        "Not pain, just tired",
        "I do not need help",
        "no need to call anyone",
        "I'm not hurt",
    ]
    for phrase in negatives_must_not:
        got = classify_reply(phrase).reply_class
        assert got != "negative", f"{phrase!r} must not classify negative (got {got})"

    still_negative = ["I need help", "I fell", "I'm in pain", "I cannot get up", "help me please"]
    for phrase in still_negative:
        assert classify_reply(phrase).reply_class == "negative", f"{phrase!r} must stay negative"

    still_positive = ["I'm fine", "I'm ok", "all good"]
    for phrase in still_positive:
        assert classify_reply(phrase).reply_class == "positive"


# ---- N6: one roster source ----------------------------------------------------


def test_n6_roster_parity():
    import sys

    sys.modules["care_ladder.api.app"]._FACILITY_STATES.clear()
    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)

    import os

    os.environ["CARE_LADDER_AUTH"] = "on"
    os.environ["SESSION_SECRET"] = "n6"
    c_pg = TestClient(create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=eng)))
    r = c_pg.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    assert r.status_code == 200
    pg_staff = {s["id"]: s["status"] for s in c_pg.get("/facility/staff").json()["staff"]}

    sys.modules["care_ladder.api.app"]._FACILITY_STATES.clear()
    os.environ.pop("CARE_LADDER_AUTH", None)  # memory mode = documented auth-off default
    os.environ.pop("DATABASE_URL", None)
    c_mem = TestClient(create_app(store=AuditStore()))
    mem_staff = {s["id"]: s["status"] for s in c_mem.get("/facility/staff").json()["staff"]}

    assert pg_staff == mem_staff, f"roster must match across PG and memory: {pg_staff} vs {mem_staff}"


# ---- N3: overrides survive restart --------------------------------------------


def test_n3_overrides_survive_restart(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "n3")
    import sys

    eng = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)

    mod = sys.modules["care_ladder.api.app"]
    mod._FACILITY_STATES.clear()
    c1 = TestClient(create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=eng)))
    c1.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    iid = c1.post("/demo/run", json={"fixture": "facility_negative_reply"}).json()["incident_id"]
    c1.post(f"/facility/alerts/{iid}/priority", json={"priority": "P2"})

    mod._FACILITY_STATES.clear()  # restart
    c2 = TestClient(create_app(store=AuditStore(), pg_session_factory=sessionmaker(bind=eng)))
    c2.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"})
    summary = c2.get("/facility/audit/summary").json()
    assert summary["overrides_today"] >= 1, "override count must survive restart"
