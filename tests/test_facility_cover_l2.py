"""Layer 2 (cover and respond): live staffing state + on-call straight page.

PRD docs/galuxium/prd-full-product-ops-spine.md (locked 2026-10-05):
- cover states: on_duty / on_break / on_call / backup, distinct from
  ``StaffMember.status`` occupancy and from ``BotThread.on_call_result``
  (family bot call outcome; never reused here).
- only owner or floor lead may edit the four live states.
- backup = registered staff on this facility roster.
- when paging on-call backup, confirm-first does not apply (straight page).
- audit page rows name who was paged and stub vs delivered.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.facility.models import Case, StaffMember
from care_ladder.facility.routing import (
    auto_route,
    build_page_message,
    pick_assignee,
    pick_on_call_target,
)
from care_ladder.facility.service import FacilityState


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify(self, message: str) -> dict:
        self.messages.append(message)
        return {"adapter": "stub", "delivered": True, "message": message}


def _member(id_: str, **kw) -> StaffMember:
    defaults = dict(
        id=id_,
        tenant_id="demo-facility",
        display_name="Staff " + id_,
        role="CNA",
        initials="S" + id_[-1].upper(),
        status="available",
    )
    defaults.update(kw)
    return StaffMember(**defaults)


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


def _state(*members: StaffMember, case: Case | None = None) -> FacilityState:
    state = FacilityState()
    state.seed_staff(list(members))
    state.open_case(case or _case())
    return state


# -- cover state model ------------------------------------------------------


def test_cover_field_defaults_on_duty():
    m = _member("st-1")
    assert m.cover == "on_duty"


def test_set_cover_roundtrip_all_four_states():
    m = _member("st-1")
    for value in ("on_duty", "on_break", "on_call", "backup"):
        m.set_cover(value)
        assert m.cover == value


def test_set_cover_rejects_unknown_value():
    m = _member("st-1")
    with pytest.raises(ValueError):
        m.set_cover("on_call_result")  # family bot call outcome; not staffing


def test_go_on_break_syncs_cover_on_break():
    m = _member("st-1")
    m.go_on_break(minutes=30)
    assert m.cover == "on_break"
    m.come_off_break()
    assert m.cover == "on_duty"


def test_set_cover_on_duty_ends_break_state():
    m = _member("st-1")
    m.go_on_break(minutes=30)
    m.set_cover("on_duty")
    assert m.status == "available"
    assert m.break_until is None


def test_cover_does_not_touch_occupancy_status():
    m = _member("st-1")
    m.set_cover("on_call")
    assert m.status == "available"
    m.status = "on_case"
    assert m.cover == "on_call"  # occupancy and availability stay separate facts


# -- on-call / backup pick --------------------------------------------------


def test_pick_on_call_target_prefers_on_call_then_backup():
    on_duty = _member("st-1")
    backup = _member("st-2", cover="backup")
    on_call = _member("st-3", cover="on_call")
    target = pick_on_call_target([on_duty, backup, on_call])
    assert target is not None
    assert target.id == "st-3"  # on call beats backup


def test_pick_on_call_target_skips_on_duty_only_roster():
    roster = [_member("st-1"), _member("st-2")]
    assert pick_on_call_target(roster) is None


def test_pick_on_call_target_pages_through_break():
    # On-call backup is the designated escalation path: a live break clock
    # does not silence the straight page (PRD: straight page, no confirm-first;
    # the pull_off_break override governs assignment, not on-call paging).
    roster = [_member("st-1", cover="on_call", status="on_break")]
    target = pick_on_call_target(roster)
    assert target is not None
    assert target.id == "st-1"


def test_pick_on_call_target_skips_on_case_member():
    roster = [_member("st-1", cover="on_call", status="on_case", active_case_id="other")]
    assert pick_on_call_target(roster) is None


def test_pick_on_call_target_roster_order_within_tier():
    a = _member("st-1", cover="backup")
    b = _member("st-2", cover="backup")
    target = pick_on_call_target([a, b])
    assert target is not None
    assert target.id == "st-1"


# -- straight page to on-call backup ----------------------------------------


def test_auto_route_falls_through_to_on_call_straight_page():
    roster = [
        _member("st-1", cover="on_duty", status="on_break"),  # on-duty cover empty
        _member("st-2", cover="on_call"),
    ]
    state = _state(*roster)
    notifier = RecordingNotifier()
    result = auto_route(state, "case-1", notifier=notifier)
    assert result is not None
    case, member, notify = result
    assert member.id == "st-2"
    assert notify["page_kind"] == "on_call"
    assert notify["straight_page"] is True  # confirm-first does not apply
    assert notify["delivered"] is True
    assert notify["adapter"] == "stub"
    assert len(notifier.messages) == 1
    # case stays unowned: on-call receives a page, not case ownership
    assert case.owner_staff_id is None


def test_auto_route_on_call_page_message_names_target():
    roster = [
        _member("st-1", cover="on_duty", status="on_break"),
        _member("st-2", cover="on_call", display_name="Priya N."),
    ]
    state = _state(*roster)
    notifier = RecordingNotifier()
    result = auto_route(state, "case-1", notifier=notifier)
    assert result is not None
    msg = notifier.messages[0]
    assert "Priya N." in msg
    assert "on call" in msg
    assert "CL-0001" in msg


def test_auto_route_prefers_assignable_on_duty_over_on_call():
    roster = [
        _member("st-1", cover="on_duty"),
        _member("st-2", cover="on_call"),
    ]
    state = _state(*roster)
    notifier = RecordingNotifier()
    result = auto_route(state, "case-1", notifier=notifier)
    assert result is not None
    case, member, notify = result
    assert member.id == "st-1"
    assert notify.get("page_kind") == "on_duty"
    assert notify.get("straight_page") is False


def test_auto_route_no_target_returns_none():
    roster = [_member("st-1", cover="on_duty", status="on_break")]
    state = _state(*roster)
    assert auto_route(state, "case-1", notifier=RecordingNotifier()) is None


def test_pick_assignee_ignores_cover_on_call_member():
    # on_call is availability for backup paging, not assignment eligibility
    roster = [
        _member("st-1", cover="on_duty", status="on_break"),
        _member("st-2", cover="on_call"),
    ]
    assert pick_assignee(roster) is None


def test_build_page_message_on_call_no_confirm_first_phrase():
    case = _case()
    member = _member("st-2", cover="on_call", display_name="Priya N.")
    msg = build_page_message(case, member, page_kind="on_call")
    assert "straight page" in msg
    assert "confirm" not in msg.lower()
    assert "\u2014" not in msg  # no em dashes


def test_page_audit_event_written_to_incident_store():
    roster = [
        _member("st-1", cover="on_duty", status="on_break"),
        _member("st-2", cover="on_call", display_name="Priya N."),
    ]
    state = _state(*roster)
    store = AuditStore()
    from care_ladder.models import AuditEvent, CueEvent, Incident

    store.save(
        Incident(
            id="inc-1",
            household_id="demo-facility",
            cue=CueEvent(kind="no_movement", confidence=0.7),
            events=[AuditEvent(tool="cue", cue_kind="no_movement")],
        )
    )
    notifier = RecordingNotifier()
    result = auto_route(state, "case-1", notifier=notifier, store=store)
    assert result is not None
    inc = store.get("inc-1")
    page_events = [e for e in inc.events if e.tool == "staff_page"]
    assert page_events, "page event must land on the case incident audit"
    detail = page_events[-1].detail
    assert detail["paged_staff_id"] == "st-2"
    assert detail["paged_staff_name"] == "Priya N."
    assert detail["page_kind"] == "on_call"
    assert detail["confirm_first"] is False  # straight page evidence
    assert detail["adapter"] == "stub"
    assert detail["delivered"] is True
    assert detail["case_human_id"] == "CL-0001"
    assert detail["place"] == "Room 204"


def test_page_audit_event_on_duty_records_confirm_policy():
    roster = [_member("st-1", cover="on_duty", display_name="Maria G.")]
    state = _state(*roster)
    store = AuditStore()
    from care_ladder.models import AuditEvent, CueEvent, Incident

    store.save(
        Incident(
            id="inc-1",
            household_id="demo-facility",
            cue=CueEvent(kind="no_movement", confidence=0.7),
            events=[AuditEvent(tool="cue", cue_kind="no_movement")],
        )
    )
    result = auto_route(state, "case-1", notifier=RecordingNotifier(), store=store)
    assert result is not None
    inc = store.get("inc-1")
    page_events = [e for e in inc.events if e.tool == "staff_page"]
    assert page_events
    detail = page_events[-1].detail
    assert detail["page_kind"] == "on_duty"
    assert detail["confirm_first"] is True  # on-duty path: spoken confirm-first applies (ran in the ladder)


def test_auto_route_fallback_without_store_no_crash():
    roster = [
        _member("st-1", cover="on_duty", status="on_break"),
        _member("st-2", cover="on_call"),
    ]
    state = _state(*roster)
    result = auto_route(state, "case-1", notifier=RecordingNotifier())
    assert result is not None  # store optional; page still happens


# -- editor gate (owner or floor lead only) ----------------------------------


@pytest.fixture()
def client(monkeypatch):
    import sys

    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "l2-cover-test")
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


def _lead_login(client):
    """Floor lead = roster member with role Lead, logging in by staff id."""
    r = client.post(
        "/auth/login",
        json={
            "email": "facility@careladder.local",
            "password": "demo-pass-facility",
            "actor_staff_id": "demo-facility-lead",
        },
    )
    assert r.status_code == 200


def test_set_cover_requires_authentication(client):
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_call"},
    )
    assert r.status_code == 401


def test_set_cover_owner_allowed(client):
    _facility_login(client)
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_call"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cover"] == "on_call"


def test_set_cover_floor_lead_allowed(client):
    _lead_login(client)
    r = client.post(
        "/facility/staff/demo-facility-jamie/cover",
        json={"cover": "backup"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cover"] == "backup"


def test_set_cover_rejected_without_owner_or_lead_role(client):
    # logged in as the tenant owner but acting as a plain caregiver
    _facility_login(client)
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_duty", "actor_staff_id": "demo-facility-jamie"},
    )
    assert r.status_code == 403
    assert "only the owner or the floor lead" in r.json()["detail"]


def test_set_cover_rejects_non_lead_actor_unknown(client):
    _facility_login(client)
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_duty", "actor_staff_id": "agency-temp-9"},
    )
    assert r.status_code == 403


def test_set_cover_unknown_cover_value_422(client):
    _facility_login(client)
    r = client.post(
        "/facility/staff/demo-facility-maria/cover",
        json={"cover": "on_call_result"},
    )
    assert r.status_code == 422


def test_set_cover_unknown_staff_404(client):
    _facility_login(client)
    r = client.post(
        "/facility/staff/nope/cover",
        json={"cover": "on_call"},
    )
    assert r.status_code == 404


def test_staff_listing_includes_cover(client):
    _facility_login(client)
    staff = client.get("/facility/staff").json()["staff"]
    assert staff and all("cover" in s for s in staff)


def test_fixture_auto_route_on_call_backup_paged(client):
    """All on-duty cover out; on-call member gets the straight page."""
    _facility_login(client)
    staff = client.get("/facility/staff").json()["staff"]
    by_name = {s["display_name"]: s for s in staff}
    # Maria + Jamie + lead on break; Alex already on break -> on-duty pool empty
    for name in ("Maria G.", "Jamie D.", "Floor Lead"):
        r = client.post(
            f"/facility/staff/{by_name[name]['id']}/break",
            json={"on_break": True, "minutes": 30},
        )
        assert r.status_code == 200
    r = client.post(
        f"/facility/staff/{by_name['Alex R.']['id']}/cover",
        json={"cover": "on_call"},
    )
    assert r.status_code == 200, r.text
    iid = client.post(
        "/demo/run", json={"fixture": "facility_negative_reply"}
    ).json()["incident_id"]
    detail = client.get(f"/facility/alerts/{iid}").json()
    case = detail["case"]
    assert case is not None
    assert case["owner_staff_id"] is None  # straight page, no ownership change
    page_rows = [e for e in detail["rungs"] if e == "staff_page"]
    assert page_rows  # page recorded on the audit timeline
    staff_after = {s["id"]: s for s in client.get("/facility/staff").json()["staff"]}
    alex = staff_after[by_name["Alex R."]["id"]]
    assert alex["cover"] == "on_call"  # straight page did not reassign or edit cover
