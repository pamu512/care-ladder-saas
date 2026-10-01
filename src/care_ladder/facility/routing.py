"""Break-aware auto-routing and page-on-assign (Mockup H / design §4.3).

Assignment pages the assignee via the facility Slack/notify path
(``NotifyChannelAdapter``). Auto-routing skips ``on_break`` staff unless a
lead ``pull_off_break`` override is used. Honesty: stub delivery when no
webhook is configured.
"""
from __future__ import annotations

from typing import Any, Protocol

from care_ladder.facility.models import Case, StaffMember


class Notifier(Protocol):
    def notify(self, message: str) -> dict[str, Any]: ...


def _default_notifier() -> Notifier:
    from care_ladder.channels.notify import NotifyChannelAdapter

    return NotifyChannelAdapter()


def _place(case: Case) -> str:
    return (case.place_label or case.room_label or "").strip() or "unknown place"


def build_page_message(
    case: Case,
    member: StaffMember,
    *,
    lead_override: bool = False,
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
    if lead_override:
        parts.append("lead override: pulled off break")
    return " · ".join(parts)


def page_assignee(
    case: Case,
    member: StaffMember,
    *,
    notifier: Notifier | None = None,
    lead_override: bool = False,
) -> dict[str, Any]:
    """Page one staff member via the facility notify adapter."""
    adapter = notifier or _default_notifier()
    message = build_page_message(case, member, lead_override=lead_override)
    return adapter.notify(message)


def pick_assignee(
    roster: list[StaffMember],
    *,
    prefer_roles: list[str] | None = None,
) -> StaffMember | None:
    """First on-duty assignable staff (skip on_break / on_case). Roster order."""
    preferred = {r.lower() for r in (prefer_roles or []) if r}

    def _ok(m: StaffMember) -> bool:
        if m.status == "on_case":
            return False
        return bool(m.assignable())

    if preferred:
        for m in roster:
            if m.role.lower() in preferred and _ok(m):
                return m
    for m in roster:
        if _ok(m):
            return m
    return None


def assign_and_page(
    state,
    case_id: str,
    staff_id: str,
    *,
    pull_off_break: bool = False,
    notifier: Notifier | None = None,
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
        case, member, notifier=notifier, lead_override=lead_override
    )
    return case, member, notify_result


def auto_route(
    state,
    case_id: str,
    *,
    notifier: Notifier | None = None,
) -> tuple[Case, StaffMember, dict[str, Any]] | None:
    """Pick an available staff member, assign, and page. No-op if already owned."""
    case = state.cases.get(case_id)
    if case is None:
        return None
    if case.owner_staff_id:
        return None
    member = pick_assignee(state.roster())
    if member is None:
        return None
    return assign_and_page(state, case_id, member.id, notifier=notifier)


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
