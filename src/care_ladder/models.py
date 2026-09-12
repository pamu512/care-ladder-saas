from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Contact(BaseModel):
    display_name: str
    phone_e164: str | None = None


class NoMovementTrigger(BaseModel):
    enabled: bool = True
    timeout_sec: int


class SimpleTrigger(BaseModel):
    enabled: bool = True


class Triggers(BaseModel):
    no_movement: NoMovementTrigger
    no_visibility: SimpleTrigger = Field(default_factory=SimpleTrigger)
    distress_heuristic: SimpleTrigger = Field(default_factory=SimpleTrigger)


# Interface alias used in the plan
TriggerConfig = Triggers


class Zone(BaseModel):
    id: str
    polygon: list[list[float]]


class QuietHours(BaseModel):
    start: str
    end: str
    policy: str


class Rung(BaseModel):
    id: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)


class CarePlan(BaseModel):
    household_id: str
    caregiver: Contact
    monitored: Contact
    zones: list[Zone] = Field(default_factory=list)
    triggers: Triggers
    rungs: list[Rung]
    quiet_hours: QuietHours | None = None
    secondary: Contact | None = None
