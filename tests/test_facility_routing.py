"""Mockup H break-aware auto-routing + page-on-assign (design §4.3)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.facility.models import Case, StaffMember
from care_ladder.facility.routing import (
    assign_and_page,
    auto_route,
    build_page_message,
    pick_assignee,
    repage_case,
)
from care_ladder.facility.service import FacilityState


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify(self, message: str) -> dict:
        self.messages.append(message)
        return {"adapter": "stub", "delivered": True, "message": message}


def _roster() -> list[StaffMember]:
    return [
        StaffMember(
            id="demo-facility-maria",
            tenant_id="demo-facility",
            display_name="Maria G.",
            role="RN",
            initials="MG",
            status="available",
        ),
        StaffMember(
            id="demo-facility-alex",
            tenant_id="demo-facility",
            display_name="Alex R.",
            role="CNA",
            initials="AR",
            status="on_break",
        ),
        StaffMember(
            id="demo-facility-jamie",
            tenant_id="demo-facility",
            display_name="Jamie D.",
            role="CNA",
            initials="JD",
            status="available",
        ),
        StaffMember(
            id="demo-facility-lead",
            tenant_id="demo-facility",
            display_name="Floor Lead",
            role="Lead",
            initials="FL",
            status="available",
        ),
    ]


def _case(**kwargs) -> Case:
    defaults = dict(
        id="case-1",
        human_id="CL-0001",
        tenant_id="demo-facility",
        incident_id="inc-1",
        room_label="204",
        place_label="Room 204",
        subject_display_name="Margaret Hale",
        origin="from_negative_reply",
        priority="P1",
        title="help needed",
    )
    defaults.update(kwargs)
    return Case(**defaults)


def _state_with_case(case: Case | None = None) -> FacilityState:
    state = FacilityState()
    state.seed_staff(_roster())
    c = case or _case()
    state.open_case(c)
    return state


# -- unit: pick / page / assign_and_page / auto_route ----------------------


def test_pick_assignee_skips_on_break_returns_maria():
    picked = pick_assignee(_roster())
    assert picked is not None
    assert picked.display_name == "Maria G."
    assert picked.id == "demo-facility-maria"


def test_pick_assignee_none_when_all_busy():
    roster = _roster()
    for m in roster:
        m.status = "on_break"
    assert pick_assignee(roster) is None
    for m in roster:
        m.status = "on_case"
        m.active_case_id = "other"
    assert pick_assignee(roster) is None


def test_assign_and_page_maria_notifies():
    state = _state_with_case()
    notifier = RecordingNotifier()
    result = assign_and_page(
        state, "case-1", "demo-facility-maria", notifier=notifier
    )
    assert result is not None
    case, member, notify = result
    assert case.owner_staff_id == "demo-facility-maria"
    assert member.status == "on_case"
    assert notify["delivered"] is True
    assert notify["adapter"] == "stub"
    assert len(notifier.messages) == 1
    msg = notifier.messages[0]
    assert "Maria G." in msg
    assert "CL-0001" in msg
    assert "P1" in msg
    assert "Room 204" in msg or "204" in msg
    assert "lead override" not in msg


def test_assign_on_break_without_override_no_notify():
    state = _state_with_case()
    notifier = RecordingNotifier()
    result = assign_and_page(
        state, "case-1", "demo-facility-alex", notifier=notifier
    )
    assert result is None
    assert notifier.messages == []
    assert state.cases["case-1"].owner_staff_id is None


def test_assign_pull_off_break_pages_with_lead_override():
    state = _state_with_case()
    notifier = RecordingNotifier()
    result = assign_and_page(
        state,
        "case-1",
        "demo-facility-alex",
        pull_off_break=True,
        notifier=notifier,
    )
    assert result is not None
    case, member, notify = result
    assert case.owner_staff_id == "demo-facility-alex"
    assert member.status == "on_case"
    assert any(o["action"] == "pull_off_break" for o in state.overrides)
    assert "lead override" in notifier.messages[0].lower()
    assert "break" in notifier.messages[0].lower()
    assert notify["delivered"] is True


def test_auto_route_assigns_maria_and_is_idempotent():
    state = _state_with_case()
    notifier = RecordingNotifier()
    first = auto_route(state, "case-1", notifier=notifier)
    assert first is not None
    assert first[0].owner_staff_id == "demo-facility-maria"
    assert len(notifier.messages) == 1
    second = auto_route(state, "case-1", notifier=notifier)
    assert second is None
    assert state.cases["case-1"].owner_staff_id == "demo-facility-maria"
    assert len(notifier.messages) == 1


def test_auto_route_none_when_nobody_available():
    state = _state_with_case()
    for m in state.staff.values():
        m.go_on_break(minutes=30)
    notifier = RecordingNotifier()
    assert auto_route(state, "case-1", notifier=notifier) is None
    assert state.cases["case-1"].owner_staff_id is None
    assert notifier.messages == []


def test_repage_owner_and_group():
    state = _state_with_case()
    notifier = RecordingNotifier()
    # unowned -> group re-page
    out = repage_case(state, "case-1", notifier=notifier)
    assert out["delivered"] is True
    assert "re-page group" in notifier.messages[0]
    # owned -> page assignee
    assign_and_page(state, "case-1", "demo-facility-jamie", notifier=notifier)
    notifier.messages.clear()
    out2 = repage_case(state, "case-1", notifier=notifier)
    assert "Jamie D." in notifier.messages[0]
    assert out2["delivered"] is True


def test_build_page_message_no_em_dash():
    msg = build_page_message(_case(), _roster()[0], lead_override=True)
    assert "—" not in msg
    assert "lead override" in msg


# -- API / fixture integration ---------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    import sys

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "facility-routing-test")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
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


def _run(client, fixture):
    r = client.post("/demo/run", json={"fixture": fixture})
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


def test_api_assign_includes_notify_stub(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    # Case may already be auto-routed; reassign to Jamie to exercise page path.
    staff = client.get("/facility/staff").json()["staff"]
    jamie = next(s for s in staff if "Jamie" in s["display_name"])
    # Put Jamie on available if needed; she starts available.
    r = client.post(
        f"/facility/alerts/{iid}/assign",
        json={"staff_id": jamie["id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["case"]["owner_staff_id"] == jamie["id"]
    assert "notify" in body
    assert body["notify"]["delivered"] is True
    assert body["notify"]["adapter"] == "stub"
    assert "Jamie" in body["notify"]["message"]


def test_api_assign_on_break_409_no_owner_change_to_alex(client):
    _facility_login(client)
    iid = _run(client, "facility_notify_silence")
    staff = client.get("/facility/staff").json()["staff"]
    alex = next(s for s in staff if "Alex" in s["display_name"])
    before = client.get(f"/facility/alerts/{iid}").json()["case"]["owner_staff_id"]
    r = client.post(f"/facility/alerts/{iid}/assign", json={"staff_id": alex["id"]})
    assert r.status_code == 409
    after = client.get(f"/facility/alerts/{iid}").json()["case"]["owner_staff_id"]
    assert after == before  # unchanged (auto-route owner or None)


def test_api_pull_off_break_notifies_lead_override(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    staff = client.get("/facility/staff").json()["staff"]
    alex = next(s for s in staff if "Alex" in s["display_name"])
    r = client.post(
        f"/facility/alerts/{iid}/assign",
        json={"staff_id": alex["id"], "pull_off_break": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case"]["owner_staff_id"] == alex["id"]
    assert "lead override" in body["notify"]["message"].lower()
    audit = client.get("/facility/audit/summary").json()
    assert audit["overrides_today"] >= 1


def test_fixture_auto_routes_to_available_not_alex(client):
    _facility_login(client)
    iid = _run(client, "facility_negative_reply")
    cases = client.get("/facility/cases").json()
    match = [c for c in cases["open"] if c["incident_id"] == iid]
    assert match, "negative reply must open a case"
    owner = match[0]["owner_staff_id"]
    assert owner is not None, "auto-route should assign an on-duty staff member"
    assert owner != "demo-facility-alex"
    staff = {s["id"]: s for s in client.get("/facility/staff").json()["staff"]}
    assert staff[owner]["status"] in ("on_case", "available")


def test_repage_override_includes_notify(client):
    _facility_login(client)
    iid = _run(client, "facility_notify_silence")
    r = client.post(
        f"/facility/alerts/{iid}/override",
        json={"action": "repage"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "paged"
    assert body["notify"]["delivered"] is True
    assert body["notify"]["adapter"] == "stub"
