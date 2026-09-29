"""Facility floor domain: reply classes, priority, staff, cases (Mockup H)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

ReplyClass = Literal["positive", "negative", "silence", "unclear"]
Priority = Literal["P1", "P2", "P3"]
CaseOrigin = Literal["from_negative_reply", "from_silence", "from_cue", "manual"]
CaseState = Literal["paged", "handling", "wrapping", "closed"]
StaffStatus = Literal["available", "on_case", "on_break"]


_LOCAL_SEQ = 0


def _default_priority(cue: str, reply_class: ReplyClass) -> Priority:
    """Documented mapping: distress cues are P1; negative replies auto-raise to P1."""
    if reply_class == "negative":
        return "P1"
    if cue == "distress_heuristic":
        return "P1"
    if cue in ("no_movement", "no_visibility"):
        return "P2"
    return "P3"


def _default_priority_classmethod_factory():
    return staticmethod(_default_priority)


Priority.default_for = staticmethod(_default_priority)  # type: ignore[attr-defined]


class StaffMember(BaseModel):
    id: str
    tenant_id: str
    display_name: str
    role: str
    initials: str
    status: StaffStatus = "available"
    break_until: datetime | None = None
    active_case_id: str | None = None

    def go_on_break(self, minutes: int, now: datetime | None = None) -> None:
        base = now or datetime.now(timezone.utc)
        self.status = "on_break"
        self.break_until = base + timedelta(minutes=minutes)

    def come_off_break(self) -> None:
        self.status = "available"
        self.break_until = None

    def assignable(self, now: datetime | None = None) -> bool:
        if self.status == "on_break":
            if self.break_until is not None:
                base = now or datetime.now(timezone.utc)
                if base >= self.break_until:
                    self.status = "available"  # break expired
                    self.break_until = None
                    return True
            return False  # requires lead pull_off_break override
        return self.status == "available"


class Case(BaseModel):
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    human_id: str = ""
    tenant_id: str
    incident_id: str
    room_label: str
    place_label: str = ""  # display place; aliases room_label when empty
    subject_display_name: str | None = None
    subject_kind: str | None = None  # child | resident | patient
    subject_id: str | None = None
    title: str
    origin: CaseOrigin
    priority: Priority
    state: CaseState = "paged"
    owner_staff_id: str | None = None
    slack_thread_url: str = ""
    ack_at: datetime | None = None
    closed_at: datetime | None = None
    documentation: str | None = None
    sla_ack_sec: int = 120
    sla_handling_sec: int = 900

    @classmethod
    def open_from_incident(
        cls,
        *,
        incident_id: str,
        tenant_id: str,
        room_label: str,
        origin: CaseOrigin,
        priority: Priority,
        title: str = "",
        human_id: str = "",
        subject_display_name: str | None = None,
        subject_kind: str | None = None,
        subject_id: str | None = None,
    ) -> "Case":
        # Callers that persist cases MUST pass human_id (state.next_human_id()
        # guarantees cross-restart uniqueness). The fallback keeps a simple
        # process-local CL- counter for non-persisted unit use.
        if not human_id:
            global _LOCAL_SEQ
            _LOCAL_SEQ += 1
            human = f"CL-{_LOCAL_SEQ:04d}"
        else:
            human = human_id
        return cls(
            tenant_id=tenant_id,
            incident_id=incident_id,
            room_label=room_label,
            place_label=room_label,
            subject_display_name=subject_display_name,
            subject_kind=subject_kind,
            subject_id=subject_id,
            origin=origin,
            priority=priority,
            title=title or f"{origin.replace('from_', '').replace('_', ' ').title()} - room {room_label}",
            human_id=human,
            slack_thread_url=f"https://example.invalid/care-floor-ops/thread/{human}",
        )

    def close(self, documentation: str, now: datetime | None = None) -> bool:
        """Close requires real documentation (min length); returns success."""
        doc = (documentation or "").strip()
        if len(doc) < 20:
            return False
        self.documentation = doc
        self.closed_at = now or datetime.now(timezone.utc)
        self.state = "closed"
        return True
