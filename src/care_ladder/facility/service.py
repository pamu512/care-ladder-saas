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
    """Facility console state (per tenant).

    In-memory caches for the console; when ``session_factory`` is attached
    (DATABASE_URL configured) every mutation write-throughs to Postgres via
    FacilityRepository so cases/staff/breaks survive restarts.
    """

    cases: dict[str, Case] = field(default_factory=dict)
    staff: dict[str, StaffMember] = field(default_factory=dict)
    overrides: list[dict[str, Any]] = field(default_factory=list)
    resident_resolved: list[dict[str, Any]] = field(default_factory=list)
    session_factory: Any = None
    _opened_times: dict[str, str] = field(default_factory=dict)

    def _repo(self, session):
        from care_ladder.facility.repository import FacilityRepository

        tenant_id = next(iter(self.staff.values())).tenant_id if self.staff else "demo-facility"
        return FacilityRepository(session, tenant_id)

    def _persist(self) -> None:
        if self.session_factory is None:
            return
        from care_ladder.db.models import CaseRow

        with self.session_factory() as session:
            repo = self._repo(session)
            for c in self.cases.values():
                if session.get(CaseRow, c.id) is None:
                    repo.open_case(c)
                else:
                    repo.save(c)
            for m in self.staff.values():
                repo.save_staff(m)

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
        self._persist()
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
        self._persist()
        return case, member

    def log_override(self, action: str, case_id: str, staff_id: str | None = None) -> None:
        self.overrides.append(
            {"action": action, "case_id": case_id, "staff_id": staff_id, "at": _now().isoformat()}
        )

    # -- cases -----------------------------------------------------------

    def open_case(self, case: Case) -> Case:
        self.cases[case.id] = case
        self._opened_times[case.id] = _now().isoformat()
        self._persist()
        return case

    def case_opened_times(self) -> dict[str, str]:
        """case_id -> ISO open time (CSV export; falls back to CaseRow.created_at)."""
        if self.session_factory is not None:
            try:
                from care_ladder.db.models import CaseRow

                with self.session_factory() as session:
                    rows = {
                        r.id: r.created_at.isoformat() if r.created_at else ""
                        for r in session.query(CaseRow).all()
                    }
                if rows:
                    return rows
            except Exception:
                pass
        return dict(self._opened_times)

    def next_human_id(self) -> str:
        """Never reissue: max existing CL-#### across this state's cases + DB."""
        import re

        def nums(cases):
            out = []
            for c in cases:
                m = re.match(r"CL-(\d+)$", c.human_id or "")
                if m:
                    out.append(int(m.group(1)))
            return out

        candidates = nums(self.cases.values())
        if self.session_factory is not None:
            try:
                from care_ladder.db.models import CaseRow

                with self.session_factory() as session:
                    for (h,) in session.query(CaseRow.human_id).all():
                        m = re.match(r"CL-(\d+)$", h or "")
                        if m:
                            candidates.append(int(m.group(1)))
            except Exception:
                pass
        return f"CL-{(max(candidates) + 1) if candidates else 1:04d}"

    def ack_case(self, case_id: str) -> Case | None:
        c = self.cases.get(case_id)
        if c is None:
            return None
        if c.ack_at is None:
            c.ack_at = _now()
        if c.state == "paged":
            c.state = "handling"
        self._persist()
        return c

    def close_case(self, case_id: str, documentation: str) -> Case | None:
        c = self.cases.get(case_id)
        if c is None or not c.close(documentation=documentation, now=_now()):
            return None
        owner = self.staff.get(c.owner_staff_id or "")
        if owner is not None:
            owner.status = "available"
            owner.active_case_id = None
        self._persist()
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
