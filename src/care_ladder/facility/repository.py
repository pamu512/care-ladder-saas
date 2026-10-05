"""Postgres repository for facility staff + cases (tenant-scoped, Mockup H)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from care_ladder.db.models import CaseRow, StaffRow
from care_ladder.facility.models import Case, StaffMember


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FacilityRepository:
    """Tenant-scoped persistence for staff roster and cases."""

    def __init__(self, session: Session, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    # -- staff -----------------------------------------------------------

    def list_staff(self) -> list[StaffMember]:
        rows = self.session.execute(
            select(StaffRow).where(StaffRow.tenant_id == self.tenant_id).order_by(StaffRow.id)
        ).scalars().all()
        return [
            StaffMember(
                id=r.id,
                tenant_id=r.tenant_id,
                display_name=r.display_name,
                role=r.role,
                initials=r.initials,
                status=r.status,  # type: ignore[arg-type]
                cover=getattr(r, "cover", "on_duty") or "on_duty",  # type: ignore[arg-type]
                break_until=r.break_until,
                active_case_id=r.active_case_id,
                parked_case_ids=list(getattr(r, "parked_case_ids", None) or []),
            )
            for r in rows
        ]

    def get_staff(self, staff_id: str) -> StaffMember | None:
        row = self.session.get(StaffRow, staff_id)
        if row is None or row.tenant_id != self.tenant_id:
            return None
        return StaffMember(
            id=row.id, tenant_id=row.tenant_id, display_name=row.display_name,
            role=row.role, initials=row.initials, status=row.status,  # type: ignore[arg-type]
            cover=getattr(row, "cover", "on_duty") or "on_duty",  # type: ignore[arg-type]
            break_until=row.break_until, active_case_id=row.active_case_id,
            parked_case_ids=list(getattr(row, "parked_case_ids", None) or []),
        )

    def set_break(self, staff_id: str, on_break: bool, minutes: int = 30) -> StaffMember | None:
        m = self.get_staff(staff_id)
        if m is None:
            return None
        if on_break:
            m.go_on_break(minutes=minutes)
        else:
            m.come_off_break()
        row = self.session.get(StaffRow, staff_id)
        if row is None or row.tenant_id != self.tenant_id:
            return None
        row.status = m.status
        row.break_until = m.break_until
        self.session.commit()
        return m

    def save_staff(self, member: StaffMember) -> None:
        row = self.session.get(StaffRow, member.id)
        if row is None or row.tenant_id != self.tenant_id:
            return
        row.status = member.status
        if hasattr(row, "cover"):
            row.cover = member.cover
        row.break_until = member.break_until
        row.active_case_id = member.active_case_id
        row.parked_case_ids = list(getattr(member, "parked_case_ids", []) or [])
        self.session.commit()

    def assign_case(self, staff_id: str, case_id: str) -> None:
        row = self.session.get(StaffRow, staff_id)
        if row is None or row.tenant_id != self.tenant_id:
            return
        row.status = "on_case"
        row.active_case_id = case_id
        self.session.commit()

    # -- cases -----------------------------------------------------------

    def open_case(self, case: Case) -> Case:
        row = CaseRow(
            id=case.id, human_id=case.human_id, tenant_id=case.tenant_id,
            incident_id=case.incident_id, room_label=case.room_label,
            place_label=case.place_label or case.room_label,
            subject_display_name=case.subject_display_name,
            subject_kind=case.subject_kind,
            subject_id=case.subject_id,
            title=case.title, origin=case.origin, priority=case.priority,
            state=case.state, owner_staff_id=case.owner_staff_id,
            slack_thread_url=case.slack_thread_url, ack_at=case.ack_at,
            closed_at=case.closed_at, documentation=case.documentation,
            handoffs=list(getattr(case, "handoffs", []) or []),
        )
        self.session.add(row)
        self.session.commit()
        return case

    def get_case(self, case_id: str) -> Case | None:
        row = self.session.get(CaseRow, case_id)
        if row is None or row.tenant_id != self.tenant_id:
            return None
        return self._to_domain(row)

    def list_cases(self, include_closed: bool = True) -> list[Case]:
        q = select(CaseRow).where(CaseRow.tenant_id == self.tenant_id).order_by(CaseRow.created_at.desc())
        if not include_closed:
            q = q.where(CaseRow.state != "closed")
        rows = self.session.execute(q).scalars().all()
        return [self._to_domain(r) for r in rows]

    def save(self, case: Case) -> None:
        row = self.session.get(CaseRow, case.id)
        if row is None:
            return
        row.state = case.state
        row.priority = case.priority
        row.owner_staff_id = case.owner_staff_id
        row.ack_at = case.ack_at
        row.closed_at = case.closed_at
        row.documentation = case.documentation
        if hasattr(row, "handoffs"):
            row.handoffs = list(getattr(case, "handoffs", []) or [])
        self.session.commit()

    @staticmethod
    def _to_domain(r: CaseRow) -> Case:
        return Case(
            id=r.id, human_id=r.human_id, tenant_id=r.tenant_id,
            incident_id=r.incident_id, room_label=r.room_label, title=r.title,
            place_label=getattr(r, "place_label", "") or "",
            subject_display_name=getattr(r, "subject_display_name", None),
            subject_kind=getattr(r, "subject_kind", None),
            subject_id=getattr(r, "subject_id", None),
            origin=r.origin,  # type: ignore[arg-type]
            priority=r.priority,  # type: ignore[arg-type]
            state=r.state,  # type: ignore[arg-type]
            owner_staff_id=r.owner_staff_id, slack_thread_url=r.slack_thread_url,
            handoffs=list(getattr(r, "handoffs", None) or []),
            ack_at=r.ack_at, closed_at=r.closed_at, documentation=r.documentation,
        )
