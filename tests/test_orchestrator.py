import asyncio
from pathlib import Path

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan


def test_silence_escalates_to_dial_and_writes_trace():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"}),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" in tools
    assert incident.events[0].cue_kind == "no_movement"


def test_ok_reply_resolves_without_dial():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["I'm fine"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" not in tools
    assert incident.status == "resolved"


def test_call_caregiver_jumps_to_dial_primary():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_visibility", confidence=0.8, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["yes call"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" in tools
    assert "jump" in tools  # skipped wait (and any non-dial) logged
    assert incident.status == "resolved"


def test_disabled_emergency_never_runs_and_jumps_logged_on_no_answer_skip():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="distress_heuristic", confidence=0.7, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(
                behavior={"caregiver": "no_answer", "secondary": "no_answer"}
            ),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "dial_contact" in tools
    assert "emergency" not in tools  # never executed as a tool event
    assert any(
        e.tool == "jump" and e.detail.get("skipped_tool") == "emergency"
        for e in incident.events
    )
    assert incident.status == "exhausted"
    # Never real 911
    assert all("911" not in str(e.detail) for e in incident.events)


def test_reperceive_appears_in_audit_trace():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["ok"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
        )
    )
    tools = [e.tool for e in incident.events]
    assert "reperceive" in tools
