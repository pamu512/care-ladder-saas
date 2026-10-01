"""Task 5: concurrency settings - one-focus assign, multi_own gate."""
import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.facility.models import Case
from care_ladder.api.app import _demo_roster_specs
from care_ladder.facility.models import StaffMember
from care_ladder.facility.service import FacilityState


def _seeded_state() -> FacilityState:
    st = FacilityState()
    st.seed_staff([StaffMember(tenant_id="demo-facility", **spec) for spec in _demo_roster_specs("demo-facility")])
    return st


@pytest.fixture()
def client_facility(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "tm-t5")
    app = create_app(store=AuditStore())
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "facility@careladder.local", "password": "demo-pass-facility"}).status_code == 200
    return c


def test_settings_pin_peek_roundtrip(client_facility):
    r = client_facility.patch(
        "/facility/settings",
        json={"concurrency": {"one_focus": True, "pin_peek": True, "pin_limit": 3, "multi_own": False}},
    )
    assert r.status_code == 200
    assert r.json()["concurrency"]["pin_peek"] is True


def test_two_open_cases_two_different_owners(client_facility):
    """Default demo: two negative fixtures -> two cases auto-routed to different staff."""
    import sys

    _appmod = sys.modules["care_ladder.api.app"]
    if hasattr(_appmod, "_FACILITY_STATES"):
        _appmod._FACILITY_STATES.clear()  # order-independent: no bleed from earlier tests
    assert client_facility.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    assert client_facility.post("/demo/run", json={"fixture": "facility_negative_reply"}).status_code == 200
    cases = client_facility.get("/facility/cases").json()["open"]
    assert len(cases) == 2
    owners = [c["owner_staff_id"] for c in cases]
    assert all(owners), "break-aware auto-route should assign each open case"
    assert owners[0] != owners[1], "one-focus auto-route must pick different staff"
    # Manual re-assign still pages an available staff member (Floor Lead).
    lead = next(
        s for s in client_facility.get("/facility/staff").json()["staff"]
        if s["display_name"] == "Floor Lead" and s["status"] == "available"
    )
    r = client_facility.post(
        f"/facility/alerts/{cases[0]['incident_id']}/assign",
        json={"staff_id": lead["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["case"]["owner_staff_id"] == lead["id"]


def test_assign_rejects_second_case_when_multi_own_off():
    """multi_own=False (default): busy staff (on_case) cannot take a second
    case; no-op per today's rules, focus unchanged."""
    st = _seeded_state()
    c1 = Case.open_from_incident(incident_id="i1", tenant_id="t", room_label="204", origin="from_silence", priority="P2")
    c2 = Case.open_from_incident(incident_id="i2", tenant_id="t", room_label="205", origin="from_silence", priority="P2")
    st.open_case(c1)
    st.open_case(c2)
    sid = next(iter(st.staff))
    out1 = st.assign(c1.id, sid)
    assert out1 is not None
    member = st.staff[sid]
    assert member.active_case_id == c1.id
    out2 = st.assign(c2.id, sid)
    assert out2 is None  # single-focus: rejected, not stolen
    assert member.active_case_id == c1.id
    assert c2.owner_staff_id is None


def test_multi_own_allows_two_active(state=None):
    st = _seeded_state()
    c1 = Case.open_from_incident(incident_id="i1", tenant_id="t", room_label="204", origin="from_silence", priority="P2")
    c2 = Case.open_from_incident(incident_id="i2", tenant_id="t", room_label="205", origin="from_silence", priority="P2")
    st.open_case(c1)
    st.open_case(c2)
    sid = next(iter(st.staff))
    st.concurrency = {"one_focus": True, "pin_peek": False, "pin_limit": 3, "multi_own": True}
    st.assign(c1.id, sid)
    st.assign(c2.id, sid)
    member = st.staff[sid]
    assert member.active_case_id == c1.id  # primary kept
    assert getattr(member, "parked_case_ids", None) == [c2.id]  # second parked


def test_ui_has_pin_peek_controls(client_facility):
    html = client_facility.get("/ui/facility/").text
    assert "pin" in html.lower()
    assert "sessionStorage" in html
