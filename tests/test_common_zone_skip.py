"""Task 3: ladder skips spoken check-in when the cue is in a common zone."""
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent


DEMO_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _plan(common: bool):
    from pathlib import Path

    from care_ladder.plan_loader import load_care_plan

    
    plan = load_care_plan(Path("configs/demo_facility.yaml"))
    plan = copy.deepcopy(plan)
    plan.zones[0].kind = "common" if common else "private"
    return plan


def _run(zone_common: bool, scripted=("ok",)):
    plan = _plan(zone_common)
    cue = CueEvent(
        kind="no_movement",
        confidence=0.9,
        detail={"zone_id": plan.zones[0].id},
    )
    return asyncio.run(run_incident(
        cue=cue,
        plan=plan,
        speaker=SpeakerSimulator(scripted=list(scripted)),
        dialer=StubDialer(behavior={"caregiver": "no_answer", "secondary": "no_answer"}),
        store=None,
        now=DEMO_NOW,
    ))


def test_common_zone_skips_speaker_prompt():
    inc = _run(zone_common=True)
    prompts = [e for e in inc.events if e.tool == "speaker_prompt"]
    # no REAL prompt: any speaker_prompt event must be an audited skip
    assert prompts, "expected an audited skip event"
    assert all(e.detail.get("skipped") for e in prompts)
    assert all(e.detail.get("reason") == "common_zone_no_spoken_checkin" for e in prompts)
    assert all(e.detail.get("zone_id") for e in prompts)


def test_private_zone_still_prompts():
    inc = _run(zone_common=False)
    tools = [e.tool for e in inc.events]
    assert "speaker_prompt" in tools


def test_no_zone_detail_still_prompts():
    """Back-compat: cues without zone info keep the spoken check-in."""
    plan = _plan(common=False)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    inc = asyncio.run(run_incident(
        cue=cue,
        plan=plan,
        speaker=SpeakerSimulator(scripted=["ok"]),
        dialer=StubDialer(behavior={}),
        store=None,
        now=DEMO_NOW,
    ))
    assert any(e.tool == "speaker_prompt" for e in inc.events)
