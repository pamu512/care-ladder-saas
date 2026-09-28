"""Facility service: alert queue, case lifecycle, staff routing, audit rollup.

View models over incidents + cases + staff (Mockup H section 4.5).
The in-memory registry is process-local (demo scope); Postgres-backed rows
are created through FacilityRepository when DATABASE_URL is configured.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from care_ladder.facility.models import Case, Priority, StaffMember


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FacilityState:
    """Process-local demo state for the facility console (per tenant)."""

    cases: dict[str, Case] = field(default_factory=dict)
    staff: dict[str, StaffMember] = field(default_factory=dict)
    overrides: list[dict[str, Any]] = field(default_factory=list)
    resident_resolved: list[dict[str, Any]] = field(default_factory=list)

    # -- staff -----------------------------------------------------------

    def seed_staff(self, members: list[StaffMember]) -> None:
        for m in members:
            self.staff.setdefault(m.id, m)

    def roster(self) -> list[StaffMember]:
        return list(self.staff.values())

    def set_break(self, staff_id: str, on_break: bool, minutes: int = 30) -> StaffMember | None:
        m = self.staff.get(staff_id)
        if m is None:
            return None
        if on_break:
            m.go_on_break(minutes=minutes)
        else:
            m.come_off_break()
        return m

    def assign(self, case_id: str, staff_id: str, *, pull_off_break: bool = False) -> tuple[Case, StaffMember] | None:
        case = self.cases.get(case_id)
        member = self.staff.get(staff_id)
        if case is None or member is None:
            return None
        if not member.assignable():
            if not pull_off_break:
                return None
            member.come_off_break()
            self.log_override("pull_off_break", case_id, staff_id)
        if member.status == "available":
            member.status = "on_case"
        member.active_case_id = case_id
        case.owner_staff_id = staff_id
        return case, member

    def log_override(self, action: str, case_id: str, staff_id: str | None = None) -> None:
        self.overrides.append(
            {"action": action, "case_id": case_id, "staff_id": staff_id, "at": _now().isoformat()}
        )

    # -- cases -----------------------------------------------------------

    def open_case(self, case: Case) -> Case:
        self.cases[case.id] = case
        return case

    def ack_case(self, case_id: str) -> Case | None:
        c = self.cases.get(case_id)
        if c is None:
            return None
        if c.ack_at is None:
            c.ack_at = _now()
        if c.state == "paged":
            c.state = "handling"
        return c

    def close_case(self, case_id: str, documentation: str) -> Case | None:
        c = self.cases.get(case_id)
        if c is None or not c.close(documentation=documentation, now=_now()):
            return None
        owner = self.staff.get(c.owner_staff_id or "")
        if owner is not None:
            owner.status = "available"
            owner.active_case_id = None
        return c

    # -- audit -----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        open_cases = [c for c in self.cases.values() if c.state != "closed"]
        closed_today = [c for c in self.cases.values() if c.state == "closed"]
        outcomes: dict[str, int] = {}
        for c in self.cases.values():
            key = c.origin.replace("from_", "").replace("_reply", "")
            outcomes[key] = outcomes.get(key, 0) + 1
        for _ in self.resident_resolved:
            outcomes["positive"] = outcomes.get("positive", 0) + 1
        return {
            "cases_open": len(open_cases),
            "cases_closed_today": len(closed_today),
            "resident_resolved_today": len(self.resident_resolved),
            "overrides_today": len(self.overrides),
            "outcomes": outcomes,
        }
