"""UI polish Task 1: owner join, opened/SLA fields, time KPIs, audit register APIs."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.db.base import create_engine_from_url
from care_ladder.db.models import Base


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "polish-t1")
    app = create_app(store=AuditStore())
    return TestClient(app)


def _facility_login(client):
    r = client.post(
        "/auth/login",
        json={"email": "facility@careladder.local", "password": "demo-pass-facility"},
    )
    assert r.status_code == 200


def _run(client, fixture):
    r = client.post("/demo/run", json={"fixture": fixture})
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


def test_case_out_includes_owner_and_opened(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    staff = client.get("/facility/staff").json()["staff"]
    maria = next(s for s in staff if "Maria" in s["display_name"])
    assert client.post(f"/facility/alerts/{iid}/assign", json={"staff_id": maria["id"]}).status_code == 200
    cases = client.get("/facility/cases").json()
    c = next(x for x in cases["open"] if x["incident_id"] == iid)
    assert c["owner_display_name"] == maria["display_name"]
    assert c["owner_initials"] == maria["initials"]
    assert c["opened_at"]
    assert c["sla_ack_sec"] == 120
    assert c["sla_handling_sec"] == 900


def test_audit_summary_time_metrics_after_ack_close(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    assert client.post(f"/facility/cases/{case['id']}/ack", json={}).status_code == 200
    assert client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Resident assisted back to bed safely."},
    ).status_code == 200
    s = client.get("/facility/audit/summary").json()
    assert s["median_ack_sec"] is not None and s["median_ack_sec"] >= 0
    assert s["median_handling_sec"] is not None and s["median_handling_sec"] >= 0
    assert s["pct_acked_in_sla"] is not None
    assert 0 <= s["pct_acked_in_sla"] <= 100
    assert "resolved_by_response" in s and "resolved_by_response_total" in s
    assert "group_timeouts" in s
    assert "median_response_sec" in s  # may be null until a positive fixture


def test_audit_register_lists_closed_and_resident(client):
    _facility_login(client)
    neg = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == neg)
    client.post(f"/facility/cases/{case['id']}/ack", json={})
    client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Checked room; resident OK after assist."},
    )
    pos = _run(client, "facility_positive_reply")
    reg = client.get("/facility/audit/register").json()
    assert reg["range"] == "today"
    kinds = {r["incident_id"]: r["kind"] for r in reg["rows"]}
    assert kinds[neg] == "staff_case"
    assert kinds[pos] == "resident_resolved"
    staff_row = next(r for r in reg["rows"] if r["incident_id"] == neg)
    assert staff_row["owner_display_name"] is None or isinstance(staff_row["owner_display_name"], str)
    assert staff_row["ack_sec"] is not None
    assert "staff -" not in (staff_row.get("owner_display_name") or "")


def test_audit_register_detail_has_timeline_and_timing(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    case = next(c for c in client.get("/facility/cases").json()["open"] if c["incident_id"] == iid)
    client.post(f"/facility/cases/{case['id']}/ack", json={})
    client.post(
        f"/facility/cases/{case['id']}/close",
        json={"documentation": "Resident assisted back to bed safely."},
    )
    d = client.get(f"/facility/audit/register/{iid}").json()
    assert d["timeline"] and any(x["tool"] for x in d["timeline"])
    assert "timing" in d and "ack_target_sec" in d["timing"]
    assert "evidence" in d and "frame_count" in d["evidence"]
    assert "overrides" in d
    assert d.get("documentation")


# ---- domain-level summary math ----


def test_summary_median_ack_and_handling():
    from datetime import datetime, timedelta, timezone

    from care_ladder.facility.models import Case
    from care_ladder.facility.service import FacilityState

    state = FacilityState()
    now = datetime.now(timezone.utc)
    c = Case.open_from_incident(
        incident_id="i1", tenant_id="demo-facility", room_label="204",
        origin="from_negative_reply", priority="P1", human_id="CL-0001",
    )
    c.ack_at = now - timedelta(seconds=30)
    c.closed_at = now
    c.state = "closed"
    state.cases[c.id] = c
    state._opened_times[c.id] = (now - timedelta(seconds=90)).isoformat()
    s = state.summary()
    assert s["median_ack_sec"] == 60
    assert s["median_handling_sec"] == 30
    assert s["pct_acked_in_sla"] == 100
