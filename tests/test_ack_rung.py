"""notify_and_await_ack rung: ack resolves, timeout escalates, audit is honest."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from care_ladder.channels.ack import AckRegistry
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.router import PageRouter
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan

_REPO = Path(__file__).resolve().parents[1]
_FACILITY = _REPO / "configs" / "demo_facility.yaml"
_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)  # outside quiet hours


class _RecordingRouter(PageRouter):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, str]] = []

    def get(self, channel_id):
        adapter = super().get(channel_id)
        outer = self

        class _Wrap:
            id = channel_id

            def notify(self, message):
                outer.sent.append((channel_id, message))
                return adapter.notify(message)

        return _Wrap()


def _plan():
    import copy

    plan = load_care_plan(_FACILITY)
    plan = copy.deepcopy(plan)
    for rung in plan.rungs:
        if rung.tool == "notify_and_await_ack":
            rung.params["ack_timeout_sec"] = 0.3
    return plan


def _cue(fixture: str) -> CueEvent:
    return CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": fixture})


def test_ack_within_window_resolves_and_stops_escalation():
    plan = _plan()
    router = _RecordingRouter()
    registry = AckRegistry(secret="t")
    incident_id = "inc-ack-ok"

    async def scenario():
        registry.schedule_auto_ack(incident_id, after_sec=0.05, by="RN Bo", channel="slack")
        return await run_incident(
            cue=_cue("ack_ok"),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            store=None,
            page_router=router,
            ack_registry=registry,
            ack_base_url="https://demo.example",
            max_ack_wait_sec=-1,
            now=_NOW,
            incident_id=incident_id,
        )

    incident = asyncio.run(scenario())
    tools = [e.tool for e in incident.events]
    assert "notify_and_await_ack" in tools
    resolve = next(e for e in incident.events if e.tool == "resolve")
    assert resolve.detail["reason"] == "caretaker_ack"
    assert resolve.detail["acked_by"] == "RN Bo"
    # escalation stopped: supervisor page and dial never fired
    assert "notify_supervisor" not in tools
    assert "dial_contact" not in tools
    assert incident.status == "resolved"
    # the page carried the signed ack link
    assert any("Acknowledge" in m and "/ack/" in m for _, m in router.sent)


def test_ack_timeout_escalates_to_supervisor_and_dial():
    plan = _plan()
    router = _RecordingRouter()
    registry = AckRegistry(secret="t")

    async def scenario():
        return await run_incident(
            cue=_cue("ack_timeout"),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            store=None,
            page_router=router,
            ack_registry=registry,
            ack_base_url="https://demo.example",
            max_ack_wait_sec=-1,
            now=_NOW,
        )

    incident = asyncio.run(scenario())
    tools = [e.tool for e in incident.events]
    assert "ack_timeout" in tools
    assert "notify_supervisor" in tools
    assert "dial_contact" in tools
    # caregiver answered → resolved at dial rung (escalation continued correctly)
    resolve = next(e for e in incident.events if e.tool == "resolve")
    assert resolve.detail["reason"] == "dial_answered"
    assert incident.status == "resolved"
    # pending window closed without ack
    assert registry.pending_list() == []


def test_max_ack_wait_bounds_demo_waits():
    """Default max_wait_sec must shrink the ack window too (snappy tests)."""
    plan = _plan()  # ack_timeout_sec 0.3
    registry = AckRegistry(secret="t")

    async def scenario():
        return await run_incident(
            cue=_cue("bounded"),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            store=None,
            page_router=PageRouter(),
            ack_registry=registry,
            now=_NOW,
        )  # no max_ack_wait_sec → capped by max_wait_sec=0.05

    import time

    t0 = time.monotonic()
    incident = asyncio.run(scenario())
    assert time.monotonic() - t0 < 2.0
    assert "ack_timeout" in [e.tool for e in incident.events]


def test_ack_run_details_recorded_in_timeline():
    plan = _plan()
    router = _RecordingRouter()
    registry = AckRegistry(secret="t")
    incident_id = "inc-detail"

    async def scenario():
        registry.schedule_auto_ack(incident_id, after_sec=0.05, by="RN Ci", channel="telegram")
        return await run_incident(
            cue=_cue("ack_detail"),
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            store=None,
            page_router=router,
            ack_registry=registry,
            ack_base_url="https://demo.example",
            max_ack_wait_sec=-1,
            now=_NOW,
            incident_id=incident_id,
        )

    incident = asyncio.run(scenario())
    ev = next(e for e in incident.events if e.tool == "notify_and_await_ack")
    assert ev.detail["ack_timeout_sec"] == 0.3
    assert "ack_deadline" in ev.detail
    resolve = next(e for e in incident.events if e.tool == "resolve")
    assert resolve.detail["ack_channel"] == "telegram"
