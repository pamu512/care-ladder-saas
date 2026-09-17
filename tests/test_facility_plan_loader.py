"""Task 3: facility care-plan template + loader validation."""

from pathlib import Path

import pytest

from care_ladder.models import CarePlan
from care_ladder.plan_loader import load_care_plan, validate_demo_phones

_REPO = Path(__file__).resolve().parents[1]
_FACILITY = _REPO / "configs" / "demo_facility.yaml"
_HOME = _REPO / "configs" / "demo_home.yaml"


def test_facility_yaml_loads_and_is_facility_mode():
    plan = load_care_plan(_FACILITY)
    assert plan.mode == "facility"
    assert plan.supervisor is not None
    assert plan.supervisor.display_name == "Floor Lead"
    assert plan.supervisor.phone_e164.startswith("+121")
    from care_ladder.plan_loader import _is_reserved_demo_phone
    assert _is_reserved_demo_phone(plan.supervisor.phone_e164)
    assert plan.notifications is not None
    assert plan.notifications.slack.enabled is True
    tools = [r.tool for r in plan.rungs]
    assert "notify_channel" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    # no emergency rung in facility template
    assert "emergency_services" not in tools
    assert all(r.params.get("contact") != "emergency" for r in plan.rungs)


def test_home_yaml_defaults_to_home_mode():
    plan = load_care_plan(_HOME)
    assert plan.mode in ("home", None) or plan.mode == "home"
    assert plan.supervisor is None
    assert plan.notifications is None


def test_facility_requires_reserved_supervisor_phone(tmp_path):
    plan = load_care_plan(_FACILITY)
    assert plan.supervisor is not None
    plan.supervisor.phone_e164 = "+12125550199"  # still reserved, different
    validate_demo_phones(plan)  # OK

    plan.supervisor.phone_e164 = "+12125551234"  # 555-12XX: NOT reserved
    with pytest.raises(ValueError, match="reserved"):
        validate_demo_phones(plan)

    plan.supervisor.phone_e164 = "+1911"  # standalone 911 form: emergency-like
    with pytest.raises(ValueError, match="emergency"):
        validate_demo_phones(plan)


def test_facility_yaml_rejects_notify_rungs_without_notifications(tmp_path):
    # facility plan with notify rungs but notifications disabled must fail validation
    text = _FACILITY.read_text(encoding="utf-8").replace("enabled: true", "enabled: false")
    p = tmp_path / "broken_facility.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="notify"):
        load_care_plan(p)


def test_home_mode_rejects_facility_rungs(tmp_path):
    # a home plan must not carry notify/supervisor rungs (mode/tool coherence)
    home_text = _HOME.read_text(encoding="utf-8")
    assert "notify_channel" not in home_text  # upstream home plan is clean
    text = home_text.replace(
        "rungs:",
        "rungs:\n  - {id: n1, tool: notify_channel}",
        1,
    )
    p = tmp_path / "home_with_notify.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="notify"):
        load_care_plan(p)
