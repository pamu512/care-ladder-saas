"""Mockup H Slice 3: facility API - negative-reply fixture, alerts, cases, staff, audit.

These tests run with auth ON (matching the design: facility console APIs are
session-guarded) and offline (no LLM credentials -> fixture path).
"""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    import sys

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "facility-test")
    appmod = sys.modules["care_ladder.api.app"]
    appmod._FACILITY_STATES.clear()
    if hasattr(appmod, "_SETTINGS_OVERRIDES"):
        appmod._SETTINGS_OVERRIDES.clear()
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200
    return r.json()


def _home_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "demo@careladder.local", "password": "demo-pass-home"},
    )
    assert r.status_code == 200


def _run(client, fixture):
    r = client.post("/demo/run", json={"fixture": fixture})
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


# -- fixture: facility_negative_reply -------------------------------------


def test_negative_reply_fixture_creates_p1_case(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    inc = client.get(f"/incidents/{iid}").json()
    tools = [e["tool"] for e in inc["events"]]
    assert "jump" in tools                      # skip wait rungs
    assert "speaker_prompt" in tools
    events = {e["tool"]: e for e in inc["events"]}
    cls = events.get("speaker_prompt", {}).get("detail", {}).get("reply_class")
    assert cls == "negative"
    # case opened, P1, stub slack url
    cases = client.get("/facility/cases").json()
    match = [c for c in cases["open"] if c["incident_id"] == iid]
    assert match, "negative reply must open a case"
    c = match[0]
    assert c["priority"] == "P1"
    assert c["origin"] == "from_negative_reply"
    assert "example.invalid" in c["slack_thread_url"]


def test_positive_fixture_resident_resolved_no_case(client):
    _facility_login(client)
    iid = _run(client, "facility_positive_reply")
    alerts = client.get("/facility/alerts").json()
    assert any(a["incident_id"] == iid for a in alerts["resident_resolved"])
    cases = client.get("/facility/cases").json()
    assert not any(c["incident_id"] == iid for c in cases["open"] + cases["closed_today"])


def test_silence_fixture_opens_case(client):
    _facility_login(client)
    iid = _run(client, "facility_notify_silence")
    cases = client.get("/facility/cases").json()
    match = [c for c in cases["open"] if c["incident_id"] == iid]
    assert match and match[0]["origin"] == "from_silence"


# -- alerts: priority queue, assign, override ------------------------------


def test_alerts_priority_order_and_assign(client):
    _facility_login(client)
    p2 = _run(client, "facility_notify_silence")       # P2 default
    p1 = _run(client, "facility_negative_reply")       # P1
    alerts = client.get("/facility/alerts").json()
    ids = [a["incident_id"] for a in alerts["queue"]]
    assert ids.index(p1) < ids.index(p2)

    staff = client.get("/facility/staff").json()["staff"]
    # Auto-route already claims Maria for the first open case; assign an
    # available on-duty staff member (Jamie) so one-focus does not 409.
    jamie = next(s for s in staff if "Jamie" in s["display_name"])
    r = client.post(f"/facility/alerts/{p1}/assign", json={"staff_id": jamie["id"]})
    assert r.status_code == 200, r.text
    detail = client.get(f"/facility/alerts/{p1}").json()
    assert detail["case"]["owner_staff_id"] == jamie["id"]
    assert "notify" in r.json()


def test_assign_skips_on_break_without_override(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    staff = client.get("/facility/staff").json()["staff"]
    alex = next(s for s in staff if "Alex" in s["display_name"])
    r = client.post(
        f"/facility/alerts/{iid}/assign", json={"staff_id": alex["id"]}
    )
    assert r.status_code == 409
    # lead override path
    r2 = client.post(
        f"/facility/alerts/{iid}/assign",
        json={"staff_id": alex["id"], "pull_off_break": True},
    )
    assert r2.status_code == 200
    # override logged
    audit = client.get("/facility/audit/summary").json()
    assert audit["overrides_today"] >= 1


def test_priority_override_logged(client):
    _facility_login(client)
    iid = _run(client, "facility_notify_silence")
    r = client.post(f"/facility/alerts/{iid}/priority", json={"priority": "P1"})
    assert r.status_code == 200
    summary = client.get("/facility/audit/summary").json()
    assert summary["overrides_today"] >= 1


# -- staff roster -----------------------------------------------------------


def test_staff_roster_and_break_toggle(client):
    _facility_login(client)
    staff = client.get("/facility/staff").json()["staff"]
    assert len(staff) >= 4  # seeded roster
    maria = next(s for s in staff if "Maria" in s["display_name"])
    r = client.post(f"/facility/staff/{maria['id']}/break", json={"on_break": True, "minutes": 15})
    assert r.status_code == 200
    got = client.get("/facility/staff").json()["staff"]
    assert next(s for s in got if s["id"] == maria["id"])["status"] == "on_break"


# -- case ack/close ---------------------------------------------------------

def test_case_ack_close_with_docs(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    cases = client.get("/facility/cases").json()
    c = next(c for c in cases["open"] if c["incident_id"] == iid)
    r = client.post(f"/facility/cases/{c['id']}/ack", json={})
    assert r.status_code == 200
    short = client.post(f"/facility/cases/{c['id']}/close", json={"documentation": "x"})
    assert short.status_code == 422
    r = client.post(
        f"/facility/cases/{c['id']}/close",
        json={"documentation": "Resident reported feeling dizzy; vitals checked and stable; MD notified."},
    )
    assert r.status_code == 200
    cases = client.get("/facility/cases").json()
    assert not any(x["id"] == c["id"] for x in cases["open"])
    assert any(x["id"] == c["id"] for x in cases["closed_today"])


def test_audit_summary_counts_track_fixtures(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    s = client.get("/facility/audit/summary").json()
    assert s["cases_open"] >= 1
    assert "outcomes" in s and s["outcomes"].get("negative") >= 1


# -- gating + isolation ------------------------------------------------------

def test_facility_api_requires_session(client):
    r = client.get("/facility/staff")
    assert r.status_code == 401


def test_home_tenant_blocked_from_facility_api(client):
    _home_login(client)
    r = client.get("/facility/staff")
    assert r.status_code == 403
