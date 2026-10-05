"""Break-aware auto-routing and page-on-assign (Mockup H / design §4.3).

Assignment pages the assignee via the facility notify path. Auto-routing
skips ``on_break`` staff unless a lead ``pull_off_break`` override is used.
Honesty: stub delivery when no webhook is configured.

Layer 2 (cover and respond, PRD ops spine): when on-duty cover is empty the
router falls through to the member marked on call / backup (registered
roster staff) with a straight page - confirm-first does not apply. The page
is recorded on the case incident audit: who was paged, page kind, adapter,
delivered vs stub.
"""
from __future__ import annotations

from typing import Any, Protocol

from care_ladder.facility.models import Case, StaffMember


class Notifier(Protocol):
    def notify(self, message: str) -> dict[str, Any]: ...


def _default_notifier() -> Notifier:
    from care_ladder.channels.notify import NotifyChannelAdapter

    return NotifyChannelAdapter()


def preferred_notifier() -> Notifier:
    """Layer 2 delivery boundary: Teams webhook first, else the Slack path.

    ``TeamsAdapter`` when TEAMS_WEBHOOK_URL is set (owned by the tenant
    admin); otherwise the existing ``NotifyChannelAdapter`` surface, which
    is Slack when SLACK_WEBHOOK_URL is set and an honest stub otherwise.
    Voice (StubDialer) stays stubbed and is not part of paging.
    """
    from care_ladder.channels.router import TeamsAdapter

    teams = TeamsAdapter()
    if teams._webhook_url:  # noqa: SLF001 - same-package honesty check
        return teams
    return _default_notifier()


def _place(case: Case) -> str:
    return (case.place_label or case.room_label or "").strip() or "unknown place"


def build_page_message(
    case: Case,
    member: StaffMember,
    *,
    lead_override: bool = False,
    page_kind: str = "on_duty",
) -> str:
    """Compose an honest staff page (no em dashes; no invented delivery claims)."""
    place = _place(case)
    parts = [
        f"Care Ladder page for {member.display_name} ({member.role})",
        f"case {case.human_id}",
        f"priority {case.priority}",
        f"place {place}",
    ]
    if case.subject_display_name:
        parts.append(f"subject {case.subject_display_name}")
    if page_kind in ("on_call", "backup"):
        parts.append("on call backup · straight page")
    if lead_override:
        parts.append("lead override: pulled off break")
    return " · ".join(parts)


def _page_audit_detail(
    case: Case,
    member: StaffMember,
    notify_result: dict[str, Any],
    *,
    page_kind: str,
    confirm_first: bool,
    lead_override: bool = False,
) -> dict[str, Any]:
    return {
        "paged_staff_id": member.id,
        "paged_staff_name": member.display_name,
        "case_id": case.id,
        "case_human_id": case.human_id,
        "place": _place(case),
        "page_kind": page_kind,
        "confirm_first": confirm_first,
        "lead_override": lead_override,
        "adapter": notify_result.get("adapter", "stub"),
        "delivered": bool(notify_result.get("delivered", False)),
    }


def _record_page_event(store, case: Case, detail: dict[str, Any]) -> None:
    """Append the staff_page event to the case incident audit (best effort)."""
    if store is None:
        return
    try:
        incident = store.get(case.incident_id)
        if incident is None:
            return
        from care_ladder.models import AuditEvent

        incident.events.append(
            AuditEvent(tool="staff_page", cue_kind=None, rung_id=None, detail=detail)
        )
        store.save(incident)
    except Exception:
        pass  # memory state still holds the page; audit append is best effort


def page_assignee(
    case: Case,
    member: StaffMember,
    *,
    notifier: Notifier | None = None,
    lead_override: bool = False,
    page_kind: str = "on_duty",
    store=None,
) -> dict[str, Any]:
    """Page one staff member via the facility notify adapter.

    Returns the notify result enriched with layer 2 honesty fields:
    ``page_kind`` (on_duty | on_call | backup), ``straight_page`` (True only
    for on-call/backup pages where confirm-first does not apply), and
    ``paged_staff`` naming who was paged. The page event lands on the case
    incident audit when a store is given.
    """
    adapter = notifier or _default_notifier()
    message = build_page_message(case, member, lead_override=lead_override, page_kind=page_kind)
    result = dict(adapter.notify(message))
    straight = page_kind in ("on_call", "backup")
    result["page_kind"] = page_kind
    result["straight_page"] = straight
    result["paged_staff"] = member.display_name
    detail = _page_audit_detail(
        case, member, result, page_kind=page_kind, confirm_first=not straight, lead_override=lead_override
    )
    _record_page_event(store, case, detail)
    return result


def pick_assignee(
    roster: list[StaffMember],
    *,
    prefer_roles: list[str] | None = None,
) -> StaffMember | None:
    """First on-duty assignable staff (skip on_break / on_case). Roster order.

    Layer 2: the primary pool is on-duty cover (``cover == on_duty``).
    Members marked on call / backup are the fallback pool
    (``pick_on_call_target``), not the first pick.
    """
    preferred = {r.lower() for r in (prefer_roles or []) if r}

    def _ok(m: StaffMember) -> bool:
        if m.status == "on_case":
            return False
        if not m.assignable():
            return False
        return m.cover == "on_duty"

    if preferred:
        for m in roster:
            if m.role.lower() in preferred and _ok(m):
                return m
    for m in roster:
        if _ok(m):
            return m
    return None


def pick_on_call_target(roster: list[StaffMember]) -> StaffMember | None:
    """Layer 2 backup paging target: on call first, then backup.

    Backup is registered staff on this facility roster by construction (the
    roster IS the facility's registered staff; there is no other source).
    Members whose occupancy is on_case or on_break are skipped: on-call
    cover is availability, not an override of occupancy or breaks.
    """
    for tier in ("on_call", "backup"):
        for m in roster:
            if m.cover != tier:
                continue
            if m.status == "on_case":
                continue  # already handling a case
            if m.assignable():
                return m
            # on-call/backup is the designated escalation path: a live break
            # clock does not silence the straight page (the floor set this
            # person as the cover for exactly this moment).
            if m.status == "on_break":
                return m
    return None


def assign_and_page(
    state,
    case_id: str,
    staff_id: str,
    *,
    pull_off_break: bool = False,
    notifier: Notifier | None = None,
    store=None,
) -> tuple[Case, StaffMember, dict[str, Any]] | None:
    """Assign then page. Returns None when assign is refused (e.g. on break)."""
    member_before = state.staff.get(staff_id)
    was_on_break = bool(member_before is not None and member_before.status == "on_break")
    result = state.assign(case_id, staff_id, pull_off_break=pull_off_break)
    if result is None:
        return None
    case, member = result
    lead_override = bool(pull_off_break and was_on_break)
    notify_result = page_assignee(
        case, member, notifier=notifier, lead_override=lead_override, store=store
    )
    return case, member, notify_result


def auto_route(
    state,
    case_id: str,
    *,
    notifier: Notifier | None = None,
    store=None,
) -> tuple[Case, StaffMember, dict[str, Any]] | None:
    """Pick an available staff member, assign, and page. No-op if already owned.

    Layer 2: when no on-duty member is assignable, fall through to the
    on-call / backup target with a straight page (no confirm-first, no case
    ownership change - the page asks them to take the case).
    """
    case = state.cases.get(case_id)
    if case is None:
        return None
    if case.owner_staff_id:
        return None
    member = pick_assignee(state.roster())
    if member is not None:
        return assign_and_page(state, case_id, member.id, notifier=notifier, store=store)
    on_call = pick_on_call_target(state.roster())
    if on_call is None:
        return None
    notify_result = page_assignee(
        case, on_call, notifier=notifier, page_kind=on_call.cover, store=store
    )
    return case, on_call, notify_result


def repage_case(
    state,
    case_id: str,
    *,
    notifier: Notifier | None = None,
) -> dict[str, Any]:
    """Re-page the owner if set; otherwise a group-style page for the case."""
    adapter = notifier or _default_notifier()
    case = state.cases.get(case_id)
    if case is None:
        return {"adapter": "stub", "delivered": False, "error": "case not found"}
    owner = state.staff.get(case.owner_staff_id or "")
    if owner is not None:
        return page_assignee(case, owner, notifier=adapter, lead_override=False)
    place = _place(case)
    message = (
        f"Care Ladder re-page group · case {case.human_id} · "
        f"priority {case.priority} · place {place}"
    )
    return adapter.notify(message)
