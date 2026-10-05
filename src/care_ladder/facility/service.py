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
    concurrency: dict[str, Any] = field(default_factory=lambda: {"one_focus": True, "pin_peek": False, "pin_limit": 3, "multi_own": False})
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

    def set_cover(self, staff_id: str, cover: str) -> StaffMember | None:
        """Layer 2 live cover edit. Validation/gating happens at the API."""
        m = self.staff.get(staff_id)
        if m is None:
            return None
        m.set_cover(cover)
        self._persist()
        return m

    def add_handoff(
        self,
        case_id: str,
        note: str,
        *,
        by_staff_id: str | None = None,
        by_name: str | None = None,
    ) -> Case | None:
        """Append a handoff note to the open case (layer 2).

        The note is a mid-case handoff field, distinct from the close
        ``documentation`` string. It is also appended to the incident audit
        (``handoff_note`` event) when a store is attached by the caller.
        """
        c = self.cases.get(case_id)
        if c is None or c.state == "closed":
            return None
        text = (note or "").strip()
        if len(text) < 5:
            return None
        entry = {
            "note": text,
            "by_staff_id": by_staff_id,
            "by_name": by_name,
            "at": _now().isoformat(),
        }
        c.handoffs.append(entry)
        self._persist()
        return c

    def assign(self, case_id: str, staff_id: str, *, pull_off_break: bool = False) -> tuple[Case, StaffMember] | None:
        case = self.cases.get(case_id)
        member = self.staff.get(staff_id)
        if case is None or member is None:
            return None
        multi_own = bool((self.concurrency or {}).get("multi_own"))
        if member.status == "on_break" and not member.assignable():
            if not pull_off_break:
                return None
            member.come_off_break()
            self.log_override("pull_off_break", case_id, staff_id)
        elif member.status == "on_case" and member.active_case_id != case_id:
            # one-focus default: a busy staff cannot take a second case.
            # multi_own: allow it, park the new case, keep the primary focus.
            if not multi_own:
                return None
            if case_id not in member.parked_case_ids:
                member.parked_case_ids.append(case_id)
            case.owner_staff_id = staff_id
            self._persist()
            return case, member
        if member.status == "available":
            member.status = "on_case"
        if case_id in member.parked_case_ids:
            member.parked_case_ids.remove(case_id)
        member.active_case_id = case_id
        case.owner_staff_id = staff_id
        self._persist()
        return case, member

    def log_override(self, action: str, case_id: str, staff_id: str | None = None) -> None:
        entry = {"action": action, "case_id": case_id, "staff_id": staff_id, "at": _now().isoformat()}
        self.overrides.append(entry)
        if self.session_factory is not None:
            try:
                from care_ladder.db.models import OverrideEventRow

                tenant_id = next(iter(self.staff.values())).tenant_id if self.staff else "demo-facility"
                with self.session_factory() as session:
                    session.add(
                        OverrideEventRow(
                            tenant_id=tenant_id, action=action,
                            case_id=case_id, staff_id=staff_id,
                        )
                    )
                    session.commit()
            except Exception:
                pass  # memory entry already recorded

    def load_overrides(self) -> None:
        """Hydrate overrides from Postgres on state creation (N3)."""
        if self.session_factory is None:
            return
        try:
            from care_ladder.db.models import OverrideEventRow

            tenant_id = next(iter(self.staff.values())).tenant_id if self.staff else "demo-facility"
            with self.session_factory() as session:
                rows = (
                    session.query(OverrideEventRow)
                    .filter(OverrideEventRow.tenant_id == tenant_id)
                    .order_by(OverrideEventRow.at)
                    .all()
                )
                self.overrides = [
                    {
                        "action": r.action,
                        "case_id": r.case_id,
                        "staff_id": r.staff_id,
                        "at": r.at.isoformat() if r.at else None,
                    }
                    for r in rows
                ]
        except Exception:
            pass

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
            if c.id in owner.parked_case_ids:
                owner.parked_case_ids.remove(c.id)
            if owner.active_case_id == c.id or owner.active_case_id is None:
                owner.status = "available"
                owner.active_case_id = None
                if not owner.parked_case_ids:
                    owner.status = "available"
                else:
                    owner.active_case_id = owner.parked_case_ids.pop(0)
        self._persist()
        return c

    # -- audit -----------------------------------------------------------

    @staticmethod
    def _median(vals: list[float]) -> float | None:
        if not vals:
            return None
        xs = sorted(vals)
        n = len(xs)
        mid = n // 2
        return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2

    def _case_open_dt(self, case_id: str):
        from datetime import datetime

        iso = self._opened_times.get(case_id)
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            return None

    def summary(self, *, response_secs: list[float] | None = None, group_timeouts: int | None = None) -> dict[str, Any]:
        open_cases = [c for c in self.cases.values() if c.state != "closed"]
        closed_today = [c for c in self.cases.values() if c.state == "closed"]
        outcomes: dict[str, int] = {}
        for c in self.cases.values():
            key = c.origin.replace("from_", "").replace("_reply", "")
            outcomes[key] = outcomes.get(key, 0) + 1
        for _ in self.resident_resolved:
            outcomes["positive"] = outcomes.get("positive", 0) + 1

        ack_secs: list[float] = []
        handling_secs: list[float] = []
        in_sla = 0
        acked = 0
        for c in closed_today:
            opened = self._case_open_dt(c.id)
            if opened and c.ack_at:
                ack = (c.ack_at - opened).total_seconds()
                ack_secs.append(ack)
                acked += 1
                if ack <= c.sla_ack_sec:
                    in_sla += 1
            if c.ack_at and c.closed_at:
                handling_secs.append((c.closed_at - c.ack_at).total_seconds())

        resolved_by_response = len(self.resident_resolved)
        cover_counts: dict[str, int] = {"on_duty": 0, "on_break": 0, "on_call": 0, "backup": 0}
        for m in self.staff.values():
            cover_counts[m.cover] = cover_counts.get(m.cover, 0) + 1
        handoff_total = sum(1 for c in self.cases.values() if getattr(c, "handoffs", None))
        return {
            "cases_open": len(open_cases),
            "cases_closed_today": len(closed_today),
            "resident_resolved_today": resolved_by_response,
            "overrides_today": len(self.overrides),
            "outcomes": outcomes,
            # layer 2 live cover + handoff rollups
            "cover": cover_counts,
            "cases_with_handoff": handoff_total,
            # time KPIs (UI polish Task 1)
            "median_ack_sec": self._median(ack_secs),
            "median_handling_sec": self._median(handling_secs),
            "pct_acked_in_sla": (100.0 * in_sla / acked) if acked else None,
            "median_response_sec": self._median(response_secs) if response_secs else None,
            "resolved_by_response": resolved_by_response,
            "resolved_by_response_total": resolved_by_response + len(closed_today),
            "group_timeouts": group_timeouts if group_timeouts is not None else
                sum(1 for c in self.cases.values() if c.origin == "from_silence"),
        }
