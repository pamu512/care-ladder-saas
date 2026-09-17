"""Tenant-scoped SQLAlchemy audit store (Galuxium SaaS).

Preserves the AuditStore surface (save/get/list_incidents) used by the API;
every query is filtered by the tenant bound at construction. Incidents and
their audit events are persisted as JSON payloads on rows keyed by tenant.
"""
from __future__ import annotations

from sqlalchemy import select

from care_ladder.audit.store import AuditStore
from care_ladder.db.models import AuditEventRow, IncidentRow
from care_ladder.models import Incident


class PostgresAuditStore:
    def __init__(self, session_factory, tenant_id: str) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._local = AuditStore()  # not used; kept for interface parity notes

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _to_row(incident: Incident, tenant_id: str) -> IncidentRow:
        return IncidentRow(
            tenant_id=tenant_id,
            incident_id=incident.id,
            payload=incident.model_dump(mode="json"),
        )

    # -- AuditStore surface ----------------------------------------------

    def save(self, incident: Incident) -> Incident:
        with self._session_factory() as s:
            row = s.get(IncidentRow, (self._tenant_id, incident.id))
            if row is None:
                row = self._to_row(incident, self._tenant_id)
                s.add(row)
            else:
                row.payload = incident.model_dump(mode="json")
            # replace audit-event rows for this incident
            for ev in s.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.tenant_id == self._tenant_id,
                    AuditEventRow.incident_id == incident.id,
                )
            ):
                s.delete(ev)
            s.flush()
            for seq, ev in enumerate(incident.events):
                s.add(
                    AuditEventRow(
                        tenant_id=self._tenant_id,
                        incident_id=incident.id,
                        seq=seq,
                        tool=getattr(ev, "tool", None),
                        payload=ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev),
                    )
                )
            s.commit()
        return incident

    def get(self, incident_id: str) -> Incident | None:
        with self._session_factory() as s:
            row = s.get(IncidentRow, (self._tenant_id, incident_id))
            if row is None:
                return None
            return Incident.model_validate(row.payload)

    def list_incidents(self) -> list[Incident]:
        with self._session_factory() as s:
            rows = s.scalars(
                select(IncidentRow).where(IncidentRow.tenant_id == self._tenant_id)
            ).all()
            return [Incident.model_validate(r.payload) for r in rows]
