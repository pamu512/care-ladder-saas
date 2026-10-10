from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from care_ladder.models import CarePlan, Contact

# NANP fiction: NPA-555-01XX (e.g. +12125550101). Also allow bare 555-01XX local form.
_RESERVED_NANP_555_01XX = re.compile(r"^\+1\d{3}55501\d{2}$")
# Emergency-like / real-emergency patterns. Always reject in demo (fail-closed).
_EMERGENCY_PATTERNS = (
    re.compile(r"(^|[^0-9])911([^0-9]|$)"),
    re.compile(r"(^|[^0-9])112([^0-9]|$)"),
    re.compile(r"(^|[^0-9])999([^0-9]|$)"),
    re.compile(r"^\+?1911$"),
    re.compile(r"^\+?911$"),
)


def _is_emergency_like(phone: str) -> bool:
    compact = phone.strip()
    return any(p.search(compact) for p in _EMERGENCY_PATTERNS)


def _is_reserved_demo_phone(phone: str) -> bool:
    return bool(_RESERVED_NANP_555_01XX.match(phone.strip()))


def validate_demo_phones(plan: CarePlan) -> None:
    """Require reserved fiction phones and reject emergency-like numbers in demo env.

    When ``CARE_LADDER_ENV=demo`` (default), every contact ``phone_e164`` must be
    NANP reserved ``NPA-555-01XX`` (``+1XX55501XX``). Emergency patterns (911, etc.)
    are always rejected in this mode. Contacts with ``phone_e164 is None`` are OK.
    """
    contacts: list[Contact] = [plan.caregiver, plan.monitored]
    if plan.secondary is not None:
        contacts.append(plan.secondary)
    if plan.supervisor is not None:
        contacts.append(plan.supervisor)

    for contact in contacts:
        phone = contact.phone_e164
        if phone is None:
            continue
        if _is_emergency_like(phone):
            raise ValueError(
                f"demo env rejects emergency-like phone for {contact.display_name!r}: "
                f"{phone!r} (never real 911; use reserved NPA-555-01XX)"
            )
        if not _is_reserved_demo_phone(phone):
            raise ValueError(
                f"demo env requires reserved NPA-555-01XX fiction phones; "
                f"got {phone!r} for {contact.display_name!r}"
            )


_FACILITY_TOOLS = frozenset({"notify_channel", "notify_supervisor", "notify_and_await_ack"})
_FAMILY_PAGE_CHANNELS = frozenset({"telegram_family", "whatsapp_family"})


def _is_family_page(rung) -> bool:
    return rung.tool == "notify_and_await_ack" and rung.params.get("channel") in _FAMILY_PAGE_CHANNELS


def validate_mode_coherence(plan: CarePlan) -> None:
    """Facility/home mode must be coherent with the plan's rungs and blocks.

    - facility rungs (notify_channel / notify_supervisor / slack-style
      notify_and_await_ack) require mode=facility and a supervisor + notifications
    - family chat pages (notify_and_await_ack + telegram_family/whatsapp_family)
      are allowed on home plans; they need telegram or whatsapp enabled
    - home plans must not carry facility (staff) notify rungs
    """
    facility_tools = {
        r.tool
        for r in plan.rungs
        if r.tool in _FACILITY_TOOLS and not _is_family_page(r)
    }
    family_pages = [r for r in plan.rungs if _is_family_page(r)]

    if plan.mode == "home" and facility_tools:
        raise ValueError(
            "home mode plan must not contain facility notify rungs "
            f"(found {sorted(facility_tools)}); use mode: facility"
        )
    if family_pages:
        notes = plan.notifications
        family_on = bool(
            notes is not None
            and (notes.telegram.enabled or notes.whatsapp.enabled)
        )
        if not family_on:
            raise ValueError(
                "family notify rungs require telegram or whatsapp enabled "
                "in notifications (without credentials the adapter stays stub)"
            )
    if plan.mode == "facility" and facility_tools:
        if plan.supervisor is None:
            raise ValueError("facility notify rungs require a supervisor contact")
        if plan.notifications is None or not plan.notifications.enabled_channels():
            raise ValueError(
                "facility notify rungs require at least one enabled notifications "
                "channel (slack/teams/whatsapp/telegram); a notify rung that "
                "cannot deliver is a silent stub"
            )


def load_care_plan(path: Path, *, env: str | None = None) -> CarePlan:
    """Load a household care plan YAML into a validated CarePlan model.

    When ``CARE_LADDER_ENV`` is ``demo`` (default if unset), phones are validated
    for reserved fiction and emergency fail-closed.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    plan = CarePlan.model_validate(data)
    mode = (env if env is not None else os.environ.get("CARE_LADDER_ENV", "demo")).lower()
    if mode == "demo":
        validate_demo_phones(plan)
    validate_mode_coherence(plan)
    return plan
