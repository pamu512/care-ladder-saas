from pathlib import Path
from care_ladder.plan_loader import load_care_plan

def test_loads_demo_home_and_keeps_emergency_disabled():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    assert plan.caregiver.display_name == "Alex"
    assert plan.caregiver.phone_e164.startswith("+121255501")
    assert plan.triggers.no_movement.timeout_sec == 900
    assert plan.rungs[0].tool == "reperceive"
    ask = next(r for r in plan.rungs if r.tool == "speaker_prompt")
    assert "Are you okay?" in ask.params["text"]
    assert "Alex" in ask.params["text"]
    emergency = next(r for r in plan.rungs if r.tool == "emergency")
    assert emergency.params.get("enabled") is False
